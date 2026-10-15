"""Capa de datos de alertas (`sibila alerta {enviar,probar,digest}`, Bloque 7).

Escritor NORMAL (db.connect) que SOLO escribe `alert_log` y `ops_metrics`
(D-B7). Orden duro: lectura → CPU pura → RED FUERA DE TX (un HTTP puede tardar
segundos; prohibido BEGIN IMMEDIATE durante la red, regla Bloque 2) → UNA tx
BEGIN IMMEDIATE final que vuelca alert_log + métricas. Riesgo aceptado y
documentado: crash entre envío y registro → posible reenvío visible en la
siguiente ejecución (duplicado, no pérdida silenciosa; registrar antes mentiría).

Reglas decididas:
- B1: el intento fallido se REGISTRA como canal='fallo:{canal}' y el historial
  de cooldown lo FILTRA (`canal NOT LIKE 'fallo:%'`): el fallo NUNCA enfría.
- B2: las inmaduras SÍ se notifican marcadas [INMADURO]; tope 'alerta' (jamás
  escalan a alarma). La marca la aplica la pura/mi línea, no el nivel.
- M2: vigilancia NUNCA tiene fila individual en alert_log (signal_id sería
  NULL y el tema irrecuperable); vive solo en el digest semanal (canal='digest').
- Historial por (tema,nivel) vía alert_log → signals → terms, ordenado ASC
  (contrato §5: la pura NO reordena). decidir/dedup_alertas son de la pura.
- Dominio de canal (A3 cerrada): 'telegram' | 'smtp' | 'digest'
  (+ 'fallo:{canal}' para intentos). Sin CHECK nuevo: disciplina + guardián.
- Red: requests/smtplib con timeout 30 s; `enviar` inyectable en tests.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

from . import SibilaError, db

log = logging.getLogger("sibila.alerta")

TIMEOUT_RED = 30                    # coherente con todo el programa (trampa 12)
CANALES = ("telegram", "smtp")      # dominio A3; 'digest' es interno del digest
VENTANA_DIGEST_DIAS = 7             # 168 h: un digest por semana (D-T7-4)

CLAVES_METRICAS = ("enviadas", "cooldown_omitidas", "fallos", "sin_credenciales")


class AlertaError(SibilaError):
    """Fallo previsto de alertas (BD, red totalmente caída, pura rechaza)."""


def _capa(capa=None):
    """Capa pura de alertas (contrato §5): Senal, ContextoDia, clasificar,
    decidir, dedup_alertas, Envio, alertas_fmt. Inyectable en tests."""
    if capa is not None:
        return capa
    from types import SimpleNamespace
    from .alertas import reglas as _r
    from .alertas import cooldown as _c
    return SimpleNamespace(
        Senal=_r.Senal, ContextoDia=_r.ContextoDia, clasificar=_r.clasificar,
        decidir=_c.decidir, dedup_alertas=getattr(_c, "dedup_alertas", None),
        Envio=_c.Envio, alertas_fmt=_r.alertas_fmt,
    )


# ---------- Red (aislada e inyectable; NUNCA dentro de una tx) ----------

def enviar_red(cfg, canal: str, mensaje: str) -> None:
    """Envío real por el canal. Lanza excepción ante fallo (el llamador la
    registra como 'fallo:{canal}'). Timeout fijo 30 s (trampa 12)."""
    if canal == "telegram":
        token = cfg.secretos.get("telegram_token")
        chat = cfg.secretos.get("telegram_chat")
        if not token or not chat:
            raise AlertaError("telegram: sin credenciales (config.local.toml)")
        import requests
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": mensaje},
                          timeout=TIMEOUT_RED)
        r.raise_for_status()
        return
    if canal == "smtp":
        clave = cfg.secretos.get("smtp_password")
        destino = cfg.secretos.get("smtp_destino")
        if not clave or not destino:
            raise AlertaError("smtp: sin credenciales (config.local.toml)")
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["Subject"] = "sibila alerta"
        msg["From"] = cfg.secretos.get("smtp_usuario", "sibila@localhost")
        msg["To"] = destino
        msg.set_content(mensaje)
        with smtplib.SMTP(cfg.secretos.get("smtp_host", "localhost"),
                          int(cfg.secretos.get("smtp_puerto", 25)),
                          timeout=TIMEOUT_RED) as s:
            s.send_message(msg)
        return
    raise AlertaError(f"canal desconocido: {canal!r}")


# ---------- Extracción (sin tx de escritura) ----------

def _senales_periodo(con, desde: str, hasta: str) -> list:
    """Signals del período (confirmado+inmaduro) agrupadas por (día,target):
    {dia, tema, target_id, target_type, status, z_r, s_cusum, p_mk}."""
    filas = con.execute(
        "SELECT s.id, s.day, s.target_type, s.target_id, s.metric, s.score,"
        " s.status, t.text FROM signals s JOIN terms t ON t.id = s.target_id"
        " WHERE s.day BETWEEN ? AND ? AND s.status IN ('confirmado', 'inmaduro')"
        " ORDER BY s.day, t.text",
        (desde, hasta)).fetchall()
    agrupado: dict = {}
    for f in filas:
        clave = (f["day"], f["target_id"])
        entrada = agrupado.setdefault(clave, {
            "signal_id": f["id"], "dia": f["day"], "tema": f["text"],
            "target_id": f["target_id"],
            "target_type": f["target_type"], "status": f["status"],
            "z_r": None, "s_cusum": None, "p_mk": None})
        if f["metric"] in ("z_r", "cusum", "mk"):
            entrada[{"z_r": "z_r", "cusum": "s_cusum", "mk": "p_mk"}[f["metric"]]] = \
                f["score"]
    return [agrupado[k] for k in sorted(agrupado)]


RACHA_DERIVADA_SIGNAL = 3   # CC-T1-2 (D-047): detecta SOLO escribe signals con
# conjunción completa (racha≥3); reconstruirla desde term_stats dejaba a
# cluster/emocion con racha_z=0 → vigilancia falsa (I7). Hecho derivado, no
# reimplantación de umbrales (la conjunción vive en la capa pura). El
# carril de vigilancia de digest (nace de term_stats SIN signal) sigue
# usando _racha_z real.


def _racha_z(con, target_id: int, dia: str) -> int:
    """Días consecutivos computables con z_r>3 terminando en `dia` (dato del
    ContextoDia; la conjunción/umbrales JAMÁS se reimplantan aquí)."""
    racha = 0
    for r in con.execute(
            "SELECT z_r FROM term_stats WHERE term_id = ? AND day <= ?"
            " ORDER BY day DESC LIMIT 60", (target_id, dia)):
        if r["z_r"] is None:
            break               # T-B5-12 CONGELADA: el día ciego ROMPE la
                                # racha (como motor.racha_alta; rev. Dijkstra B2)
        if r["z_r"] > 3:
            racha += 1
        else:
            break
    return racha


def _alertas_previas_7d(con, target_id: int, dia: str) -> int:
    ini = (date.fromisoformat(dia) - timedelta(days=7)).isoformat()
    return con.execute(
        "SELECT COUNT(DISTINCT day) FROM signals WHERE target_id = ?"
        " AND day < ? AND day >= ? AND metric = 'z_r'"
        " AND status IN ('confirmado', 'inmaduro')",   # CC-T1-1: una
        (target_id, dia, ini)).fetchone()[0]           # 'descartado' NO es
                                                       # alerta previa (B1)


def _historial(con) -> dict:
    """{tema: [(nivel, sent_at datetime tz-aware)]} SOLO con envíos reales:
    canal NOT LIKE 'fallo:%' (B1: el fallo no enfría, trampa 9). ASC (M3)."""
    filas = con.execute(
        "SELECT l.nivel, l.sent_at, t.text FROM alert_log l"
        " JOIN signals s ON s.id = l.signal_id JOIN terms t ON t.id = s.target_id"
        " WHERE l.canal NOT LIKE 'fallo:%' ORDER BY l.sent_at ASC, l.rowid ASC")
    out: dict = {}
    for f in filas:
        dt = datetime.strptime(f["sent_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        out.setdefault(f["text"], []).append((f["nivel"], dt))
    return out


def _canales_habilitados(cfg) -> "tuple[list[str], list[str]]":
    """(habilitados, avisos). Sin credenciales → AVISO y se intenta el otro
    (trampa 10; aislamiento por canal, patrón ingesta)."""
    avisos = []
    hab = []
    if cfg.secretos.get("telegram_token") and cfg.secretos.get("telegram_chat"):
        hab.append("telegram")
    else:
        avisos.append("telegram: sin credenciales (config.local.toml)")
    if cfg.secretos.get("smtp_password") and cfg.secretos.get("smtp_destino"):
        hab.append("smtp")
    else:
        avisos.append("smtp: sin credenciales (config.local.toml)")
    return hab, avisos


def _fmt_h(dt_txt: str) -> str:
    """Horas desde dt_txt hasta ahora (para la línea de cooldown del CLI)."""
    return dt_txt  # la pura da el motivo; aquí solo contexto


def ejecutar(cfg, con, *, desde: str, hasta: str, ahora=None, enviar=None,
             capa=None) -> dict:
    """`alerta enviar`: clasifica → cooldown (puro) → envía (fuera de tx) →
    registra (UNA tx final). Devuelve contadores, líneas y avisos para el CLI.
    `ahora` datetime tz-aware UTC inyectable (guardián: la pura no tiene reloj)."""
    capa = _capa(capa)
    enviar = enviar or enviar_red
    ahora = ahora or datetime.now(timezone.utc)
    ahora_txt = ahora.strftime("%Y-%m-%dT%H:%M:%SZ")
    cont = {k: 0 for k in CLAVES_METRICAS}
    lineas: list = []
    avisos: list = []
    senales = _senales_periodo(con, desde, hasta)
    if not senales:
        return {"contadores": cont, "lineas": lineas, "avisos": avisos,
                "sin_alertas": True}
    canales, avisos_canal = _canales_habilitados(cfg)
    avisos.extend(avisos_canal)
    if not canales:
        cont["sin_credenciales"] = 1
    historial = _historial(con)
    # FASE CPU pura: nivel por señal (las inmaduras se notifican con marca;
    # vigilancia NO se envía ni registra individualmente — trampa 11/M2)
    pendientes = []   # (entrada, nivel)
    vigilancias = 0
    for s in senales:
        ctx = capa.ContextoDia(
            z_r=_dec(s["z_r"]), p_mk=_dec(s["p_mk"]), s_cusum=_dec(s["s_cusum"]),
            racha_z=RACHA_DERIVADA_SIGNAL,
            status=s["status"],
            alertas_previas_tema_7d=_alertas_previas_7d(con, s["target_id"], s["dia"]))
        senal = capa.Senal(tema=s["tema"], target_type=s["target_type"],
                           status=s["status"], day=date.fromisoformat(s["dia"]))
        nivel = capa.clasificar(senal, ctx)
        if nivel is None:
            continue
        if s["status"] == "inmaduro" and nivel == "alarma":
            nivel = "alerta"     # B2: las inmaduras NUNCA escalan (vector iii)
        if nivel == "vigilancia":
            vigilancias += 1    # solo digest semanal; sin fila individual (M2)
            continue
        pendientes.append((s, nivel))
    nuevas = tuple((s["tema"], nivel) for s, nivel in pendientes)
    hist_envios = []
    for tema in sorted(historial):
        for nivel, sent in historial[tema]:
            hist_envios.append(capa.Envio(tema=tema, nivel=nivel, sent_at=sent))
    hist_envios = tuple(hist_envios)  # ya ASC por sent_at (SQL ORDER BY)
    if getattr(capa, "dedup_alertas", None):
        emitir, _supr = capa.dedup_alertas(nuevas, hist_envios, ahora)
        emitir_lista = list(emitir)
    else:  # fachada mínima: iterar decidir añadiendo al historial efectivo
        emitir_lista = []
        efectivo = list(hist_envios)
        for tema, nivel in nuevas:
            d = capa.decidir(tema, nivel, tuple(efectivo), ahora)
            if d.enviar:
                emitir_lista.append((tema, nivel))
                efectivo.append(capa.Envio(tema=tema, nivel=nivel,
                                           sent_at=ahora))
    a_enviar = len(emitir_lista)
    # FASE RED (fuera de tx) — aislamiento por canal (patrón ingesta).
    # Emparejamiento POSICIONAL con la salida de dedup (rev. Dijkstra M1:
    # misma (tema,nivel) dos días del rango → UN envío y una omitida; con
    # pertenencia por conjunto se enviaban AMBAS y se registraban ambas).
    registros = []    # (signal_id, nivel, canal)
    for s, nivel in pendientes:
        try:
            emitir_lista.remove((s["tema"], nivel))
        except ValueError:
            cont["cooldown_omitidas"] += 1
            lineas.append(("INFO", f"cooldown: {s['tema']} omitida "
                                   f"(ya notificada dentro de la ventana)"))
            continue
        marca = "[INMADURO] " if s["status"] == "inmaduro" else ""
        mensaje = f"{marca}sibila {nivel}: {s['tema']} (z_r {s['z_r']}, {s['dia']})"
        ok_canal = None
        for canal in canales:
            try:
                enviar(cfg, canal, mensaje)
                ok_canal = ok_canal or canal
                registros.append((s["signal_id"], nivel, canal))
                lineas.append(("OK", f"{canal}: {s['tema']} nivel {nivel}"))
            except Exception as e:
                cont["fallos"] += 1
                registros.append((s["signal_id"], nivel, f"fallo:{canal}"))
                lineas.append(("FALLO", f"{canal}: {e}"))
        if ok_canal:
            cont["enviadas"] += 1
    # FASE BD: UNA tx final con TODO alert_log + métricas (trampa 10/§4)
    with db.tx(con):
        for signal_id, nivel, canal in registros:
            con.execute(
                "INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                " VALUES (?, ?, ?, ?)", (signal_id, nivel, canal, ahora_txt))
        ts = db.now_iso()
        for clave in CLAVES_METRICAS:
            con.execute("INSERT INTO ops_metrics(ts, clave, valor) VALUES (?, ?, ?)",
                        (ts, f"alerta.{clave}", float(cont[clave])))
    cont["_vigilancias_digest"] = vigilancias
    todos_caidos = bool(pendientes) and bool(canales) and cont["enviadas"] == 0 \
        and cont["fallos"] > 0
    return {"contadores": cont, "lineas": lineas, "avisos": avisos,
            "sin_alertas": not pendientes, "a_enviar": a_enviar,
            "todos_caidos": todos_caidos}


def _dec(v):
    """float → Decimal 4dec para la pura (None pasa como None → n/d).
    ROUND_HALF_UP explícito (norma del proyecto B5; rev. Dijkstra M5)."""
    from decimal import ROUND_HALF_UP, Decimal
    return None if v is None else Decimal(str(v)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)


def probar(cfg, con, *, ahora=None, enviar=None, capa=None) -> dict:
    """TP-N7: mensaje de prueba por el primer canal habilitado. El intento se
    REGISTRA en alert_log aunque falle (V9: 'aplazado con causa' documentado)."""
    capa = _capa(capa)
    enviar = enviar or enviar_red
    ahora_txt = (ahora or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    canales, avisos = _canales_habilitados(cfg)
    if enviar is not enviar_red and not canales:
        canales = ["telegram"]          # canal falso inyectado en tests (TP-N7)
    if not canales:
        with db.tx(con):  # el intento fallido también se registra (V9)
            con.execute("INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                        " VALUES (NULL, 'alerta', 'fallo:telegram', ?)", (ahora_txt,))
        return {"ok": False, "canal": None, "avisos": avisos,
                "error": "sin credenciales en ningún canal"}
    canal = canales[0]
    try:
        enviar(cfg, canal, "sibila: mensaje de prueba (alerta probar)")
    except Exception as e:
        with db.tx(con):
            con.execute("INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                        " VALUES (NULL, 'alerta', ?, ?)", (f"fallo:{canal}", ahora_txt))
        return {"ok": False, "canal": canal, "avisos": avisos, "error": str(e)}
    with db.tx(con):
        con.execute("INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                    " VALUES (NULL, 'alerta', ?, ?)", (canal, ahora_txt))
    return {"ok": True, "canal": canal, "avisos": avisos, "error": None}


def digest(cfg, con, *, desde: str, hasta: str, ahora=None, enviar=None,
           capa=None) -> dict:
    """Digest semanal (spec §9): resume vigilancias/alertas de la semana y se
    REGISTRA a sí mismo canal='digest' (anti-duplicación: mismo período →
    omitido, ventana 168 h por construcción — trampa 11/D-T7-3)."""
    capa = _capa(capa)
    enviar = enviar or enviar_red
    ahora = ahora or datetime.now(timezone.utc)
    ahora_txt = ahora.strftime("%Y-%m-%dT%H:%M:%SZ")
    previo = con.execute(
        "SELECT MAX(sent_at) FROM alert_log WHERE canal = 'digest'").fetchone()[0]
    if previo:
        ult = datetime.strptime(previo, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        if (ahora - ult) < timedelta(days=VENTANA_DIGEST_DIAS):
            return {"enviado": False, "motivo": f"digest ya enviado el {previo}",
                    "lineas": 0}
    senales = _senales_periodo(con, desde, hasta)
    niveles = []
    for s in senales:
        ctx = capa.ContextoDia(
            z_r=_dec(s["z_r"]), p_mk=_dec(s["p_mk"]), s_cusum=_dec(s["s_cusum"]),
            racha_z=RACHA_DERIVADA_SIGNAL, status=s["status"],
            alertas_previas_tema_7d=_alertas_previas_7d(con, s["target_id"], s["dia"]))
        senal = capa.Senal(tema=s["tema"], target_type=s["target_type"],
                           status=s["status"], day=date.fromisoformat(s["dia"]))
        niveles.append((s, capa.clasificar(senal, ctx)))
    cuerpo = [f"sibila digest {desde}..{hasta}"]
    for s, nivel in niveles:
        if nivel:
            cuerpo.append(f"{nivel}: {s['tema']} ({s['dia']})")
    # Carril vigilancia desde la FUENTE REAL (rev. Dijkstra B3, bloqueante):
    # detecta solo escribe signals con la conjunción plena, así que una
    # vigilancia real NUNCA tiene fila en signals; vive en term_stats
    # (z_r>3 con racha 1-2 y sin conjunción). Sin esta consulta el carril
    # estaba muerto en producción.
    for v in con.execute(
            "SELECT ts.day, ts.term_id, ts.z_r, t.text, t.type FROM term_stats ts"
            " JOIN terms t ON t.id = ts.term_id"
            " WHERE ts.day BETWEEN ? AND ? AND ts.z_r > 3"
            " AND NOT EXISTS (SELECT 1 FROM signals s"
            "                 WHERE s.target_id = ts.term_id AND s.day = ts.day"
            "                 AND s.status IN ('confirmado', 'inmaduro'))"
            # M1: una señal 'descartado'/'reactivo' NO suprime la vigilancia
            " ORDER BY ts.day, t.text", (desde, hasta)):
        ctx = capa.ContextoDia(
            z_r=_dec(v["z_r"]), p_mk=None, s_cusum=None,
            racha_z=_racha_z(con, v["term_id"], v["day"]), status="confirmado",
            alertas_previas_tema_7d=0)
        senal = capa.Senal(tema=v["text"], target_type=v["type"],
                           status="confirmado", day=date.fromisoformat(v["day"]))
        if capa.clasificar(senal, ctx) == "vigilancia":
            cuerpo.append(f"vigilancia: {v['text']} ({v['day']})")
    if len(cuerpo) == 1:
        cuerpo.append("(sin alertas en la semana)")
    canales, avisos = _canales_habilitados(cfg)
    if enviar is not enviar_red and not canales:
        canales = ["telegram"]
    ok = False
    error = None
    for canal in canales[:1]:
        try:
            enviar(cfg, canal, "\n".join(cuerpo))
            ok = True
        except Exception as e:
            error = str(e)
    with db.tx(con):
        con.execute("INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                    " VALUES (NULL, 'vigilancia', ?, ?)",
                    ("digest" if ok else "fallo:digest", ahora_txt))
    return {"enviado": ok, "motivo": None if ok else (error or "sin canales"),
            "lineas": len(cuerpo) - 1, "avisos": avisos}

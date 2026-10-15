"""Capa de datos de la detección temporal (`sibila detecta`, Bloque 5).

ÚNICO módulo del bloque que toca SQLite (D-B5-01: CERO tablas nuevas; las
fórmulas viven en sibila/deteccion/ — capa pura de Turing, SIN reloj ni BD).
Reglas de oro:
- UNA tx BEGIN IMMEDIATE POR DÍA (D-B5-02); CPU y lecturas preparatorias fuera.
- term_stats.z_r se escribe UPDATE-only: JAMÁS se toca docs/occ/df (M7) y el
  UPDATE debe existir (término del día ausente = bug visible, trampa 8).
- signals del día: DELETE (status != 'reactivo') + re-INSERT recomputado
  (TP-N8); 'reactivo' (bloque GDELT) sobrevive. Status: alerta ∧ historia≥28 →
  'confirmado'; alerta ∧ historia<28 → 'inmaduro' (N1/N2). Sin fila sin alerta.
- Series materializadas t−56…t (D-B5-04): 0.0 = día con corpus sin el ítem
  (solo términos: ausencia real); None = día hueco, fuera de historia, o —
  para emoción — día con corpus SIN medición (falta de medición ≠ 0,0;
  rev. Dijkstra M2). Look-ahead prohibido: day <= d (T3).
- Gates ANTES de escribir: día parcial (trampa 14: jamás z_r huérfano; la
  comparación la hace series.es_dia_parcial — UNA sola fuente, rev. Hamilton
  M1/Dijkstra B2), día hueco, día sin procesar (trampa 13). El día parcial SÍ
  entra en baselines futuras con su valor real (M5) — la materialización no
  excluye nada.
- La conjunción de alerta JAMÁS se reimplanta en SQL: sale de motor.evaluar.
- D-042: la elegibilidad es DATO del motor (la calcula esta capa por carril):
  series.elegible (media docs ≥5, 28 días previos) para términos; para
  emoción, el gate n_efectivo ≥ MIN_N_EFECTIVO_EMO del día evaluado (ya
  aplicado en _items_emocion → elegible=True). Nunca se aplica la media ≥5 a
  valence ∈ [−1,1] (haría la alerta de emoción inalcanzable, rev. Dijkstra B1).
- Clúster por PROPAGACIÓN (E2): sin serie propia; cuando un miembro alerta se
  materializa la fila del clúster del día (target_id por cluster_key).
- Métrica detecta.items_ciego: cuenta ÍTEMS ciegos (z_r no computable), no
  días — renombrada desde dias_ciego para decir lo que mide (rev. Hamilton
  M4b); el aviso E3 sugiere re-ejecutar desde el día SIGUIENTE al último con
  signals (rev. Hamilton M4a).
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import statistics
from datetime import date, datetime, timedelta
from decimal import Decimal

from . import SibilaError, db
from .procesa import _alta_term, _limpiar_doc, _secuencias
from .procesado import ngramas

log = logging.getLogger("sibila.detecta")

VENTANA_SERIE = 56          # t−56…t (B1: la recursión CUSUM exige 57 posiciones)
VENTANA_ELEGIBILIDAD = 28   # media de los 28 días previos (N8, fórmula de Turing)
DIAS_MADUREZ = 28           # historia mínima para status 'confirmado' (spec §7)
MIN_N_EFECTIVO_EMO = 10.0   # emoción: solo si n_efectivo ≥ 10 el día evaluado

# Las 10 claves ops_metrics por día (§5.1 del plan).
CLAVES_METRICAS = ("dias_evaluados", "elegibles", "alertas", "alertas_inmaduras",
                   "items_ciego", "dia_parcial", "dia_hueco", "dia_sin_procesar",
                   "mes_inmaduro", "zr_escritos")

METRICAS_SIGNAL = ("z_r", "cusum", "mk")   # score: z_r→z_r, cusum→S_t, mk→p (§4.5)


class DetectaError(SibilaError):
    """Fallo de BD/constraint o inconsistencia interna: aborta visible (D-B5-02)."""


def _capa(motor, series):
    """Resuelve la capa pura: inyectada en tests (dobles del contrato §3) o la
    real de sibila/deteccion (import perezoso: el resto del paquete no la exige)."""
    if motor is None or series is None:
        from .deteccion import motor as _m, series as _s
        motor = motor or _m
        series = series or _s
    return motor, series


def _fecha(txt: str) -> date:
    return date.fromisoformat(txt)


def _dias_calendario(desde: str, hasta: str) -> list:
    """Calendario CONTINUO ASC desde..hasta (los huecos son datos: None)."""
    a, b = _fecha(desde), _fecha(hasta)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def primer_dia_stats(con) -> "str | None":
    """Primer día con stats (term_stats o emo_stats); None si el sistema nace."""
    filas = []
    for tabla in ("term_stats", "emo_stats"):
        r = con.execute(f"SELECT MIN(day) FROM {tabla}").fetchone()[0]
        if r is not None:
            filas.append(r)
    return min(filas) if filas else None


def _mediana_28d(con, d: str) -> "float | None":
    """Mediana de docs/día de los 28 días previos CON documentos (SIN excluir
    parciales — prohibida la exclusión circular, M5/N4)."""
    prev = [r[0] for r in con.execute(
        "SELECT COUNT(*) FROM documents WHERE dia < ? AND dia >= ? GROUP BY dia",
        (d, (_fecha(d) - timedelta(days=28)).isoformat()))]
    return statistics.median(prev) if prev else None


def _serie_item(con, tabla, col, where, params, d: str, corpus: set, series,
                *, cero_si_ausente: bool = True):
    """SerieDiaria materializada t−56…t (D-B5-04): None si el día es hueco o
    anterior a la historia. Con corpus y sin fila del ítem: 0.0 para términos
    (ausencia real) pero None para emoción (cero_si_ausente=False: un día sin
    fila emo_stats es 'no medido', jamás valence 0,0 — rev. Dijkstra M2)."""
    dias = _dias_calendario((_fecha(d) - timedelta(days=VENTANA_SERIE)).isoformat(), d)
    filas = con.execute(
        f"SELECT day, {col} FROM {tabla} WHERE {where} AND day <= ? AND day >= ?"
        f" ORDER BY day ASC", (*params, d, dias[0])).fetchall()
    valores_dia = {r["day"]: r[col] for r in filas}
    valores = tuple(None if (dia not in corpus
                             or (not cero_si_ausente and dia not in valores_dia))
                    else float(valores_dia.get(dia, 0.0))
                    for dia in dias)
    return series.SerieDiaria(dias=tuple(dias), valores=valores)


def _items_del_dia(con, d: str):
    """Candidatos del día: (target_type, clave, term_id|lang, serie-params).
    Solo ítems CON fila en term_stats del día (o emo_stats con n_efectivo≥10).
    Determinista: ORDER BY term_id."""
    items = []
    for r in con.execute(
            "SELECT ts.term_id, t.type, t.text FROM term_stats ts"
            " JOIN terms t ON t.id = ts.term_id"
            " WHERE ts.day = ? AND t.type IN ('term','bigram','trigram')"
            " ORDER BY ts.term_id ASC", (d,)):
        items.append({"tipo": r["type"], "term_id": r["term_id"], "texto": r["text"]})
    return items


def _items_emocion(con, d: str):
    """Emoción por lang SOLO si n_efectivo ≥ 10 ese día (§3; vetada si no)."""
    return [r["lang"] for r in con.execute(
        "SELECT lang FROM emo_stats WHERE day = ? AND n_efectivo >= ?"
        " ORDER BY lang ASC", (d, MIN_N_EFECTIVO_EMO))]


def _clusteres_del_dia(con, d: str) -> dict:
    """{term_id_miembro: (cluster_term_id, [ids miembros])} del día, recomputando
    la clusterización desde documents (misma entrada determinista que procesa;
    cooc no se persiste). Vacío si el día no tiene elegibles."""
    elegibles = con.execute(
        "SELECT body_text, lang FROM documents WHERE dia = ?"
        " AND duplicate_of IS NULL AND lang IS NOT NULL ORDER BY id ASC", (d,)).fetchall()
    if not elegibles:
        return {}
    df: dict = {}
    cooc: dict = {}
    sets_docs = []
    for e in elegibles:
        terms, _big, _tri = _secuencias(_limpiar_doc(e["body_text"]), e["lang"])
        s = set(terms)
        sets_docs.append(s)
        for t in s:
            df[t] = df.get(t, 0) + 1
    for s in sets_docs:
        miembros = sorted(t for t in s if df.get(t, 0) >= ngramas._DF_MIN)
        for x in range(len(miembros)):
            for y in range(x + 1, len(miembros)):
                par = (miembros[x], miembros[y])
                cooc[par] = cooc.get(par, 0) + 1
    stats = ngramas.StatsDia(df=df, docs_elegibles=len(elegibles), cooc=cooc)
    id_por_texto = {r["text"]: r["id"] for r in con.execute(
        "SELECT id, text FROM terms WHERE type = 'term'")}
    out: dict = {}
    for clu in ngramas.clusterizar(stats):
        ids = []
        for t in clu.miembros:
            if t not in id_por_texto:
                raise DetectaError(f"término {t!r} del clúster ausente en terms")
            ids.append(id_por_texto[t])
        clave = hashlib.sha256(
            ",".join(str(i) for i in sorted(ids)).encode("ascii")).hexdigest()
        fila = con.execute(
            "SELECT id FROM terms WHERE type = 'cluster' AND cluster_key = ?",
            (clave,)).fetchone()
        if fila is None:
            raise DetectaError(
                f"clúster {clave[:16]} del día {d} ausente en terms "
                "(¿procesa no llegó a escribirlo?)")
        for mid in ids:
            out[mid] = (fila["id"], sorted(ids))
    return out


def detectar_dia(con, d: str, *, motor, series, historia: int,
                 ahora_txt=None) -> dict:
    """Evalúa UN día: lectura → CPU pura → UNA tx. Devuelve contadores del día
    y 'senales' = filas signals insertadas (contrato §4.2: detecta(dia) → int).
    historia = días de calendario desde el primer día con stats (N2)."""
    cont = {k: 0 for k in CLAVES_METRICAS}
    # --- FASE LECTURA (sin tx de escritura) ---
    docs_dia = con.execute(
        "SELECT COUNT(*) FROM documents WHERE dia = ?", (d,)).fetchone()[0]
    if docs_dia == 0:
        cont["dia_hueco"] = 1
        _persistir_dia(con, d, cont, [], [])
        return cont
    sin_procesar = con.execute(
        "SELECT COUNT(*) FROM documents WHERE dia = ? AND calidad_score IS NULL",
        (d,)).fetchone()[0]
    if sin_procesar:  # trampa 13: ceros ficticios prohibidos
        cont["dia_sin_procesar"] = 1
        _persistir_dia(con, d, cont, [], [])
        return cont
    mediana = _mediana_28d(con, d)
    if mediana is not None and series.es_dia_parcial(docs_dia, mediana):
        # Gate ANTES de escribir (trampa 14): ni z_r ni signals del día.
        # La comparación vive SOLO en series.es_dia_parcial (rev. B2/M1).
        cont["dia_parcial"] = 1
        _persistir_dia(con, d, cont, [], [])
        return cont
    if historia < DIAS_MADUREZ:
        cont["mes_inmaduro"] = 1
    cont["dias_evaluados"] = 1
    corpus = {r[0] for r in con.execute(
        "SELECT DISTINCT dia FROM documents WHERE dia <= ? AND dia >= ?",
        (d, (_fecha(d) - timedelta(days=VENTANA_SERIE)).isoformat()))}

    # --- FASE CPU (pura; la conjunción vive en motor.evaluar) ---
    evaluaciones = []   # (item, EvalItem, alerta_final, status)
    for item in _items_del_dia(con, d):
        serie = _serie_item(con, "term_stats", "docs", "term_id = ?",
                            (item["term_id"],), d, corpus, series)
        # D-042: la elegibilidad la calcula la capa y entra como dato
        elegible = series.elegible(serie.valores[-VENTANA_ELEGIBILIDAD - 1:-1])
        ev = motor.evaluar(serie, elegible=elegible)
        if elegible:
            cont["elegibles"] += 1
        if ev.z_r is None:
            cont["items_ciego"] += 1
        alerta = bool(ev.alerta) and elegible
        evaluaciones.append((item, ev, alerta))
    emos = []
    for lang in _items_emocion(con, d):
        serie = _serie_item(con, "emo_stats", "valence_mean",
                            "lang = ?", (lang,), d, corpus, series,
                            cero_si_ausente=False)   # no medido ≠ 0,0 (M2)
        # D-042: emoción elegible por el gate n_efectivo≥10 del día (aplicado
        # en _items_emocion); JAMÁS la media≥5 sobre valence (rev. Dijkstra B1)
        ev = motor.evaluar(serie, elegible=True)
        cont["elegibles"] += 1      # el gate n_efectivo≥10 ya filtró (§3)
        if ev.z_r is None:
            cont["items_ciego"] += 1
        emos.append(({"tipo": "emocion", "lang": lang}, ev, bool(ev.alerta)))
    status = "inmaduro" if cont["mes_inmaduro"] else "confirmado"
    cont["alertas"] = sum(1 for _, _, a in evaluaciones + emos if a)
    if status == "inmaduro":
        cont["alertas_inmaduras"] = cont["alertas"]

    # Propagación a clústeres (E2): solo si algún miembro alerta; el clúster
    # no tiene serie propia. Score = la del miembro disparador de mayor z_r.
    cluster_rows = []
    alertantes = [(it, ev) for it, ev, a in evaluaciones if a
                  and it["tipo"] == "term"]
    if alertantes:
        clusteres = _clusteres_del_dia(con, d)
        por_cluster: dict = {}
        for it, ev in alertantes:
            entrada = clusteres.get(it["term_id"])
            if entrada is None:
                continue
            cid = entrada[0]
            if cid not in por_cluster or (ev.z_r is not None and
                                          ev.z_r > por_cluster[cid][1].z_r):
                por_cluster[cid] = (it, ev)
        for cid in sorted(por_cluster):
            cluster_rows.append((cid, por_cluster[cid][1]))

    # --- FASE BD (UNA tx BEGIN IMMEDIATE por día) ---
    senales = _persistir_dia(con, d, cont, evaluaciones, emos,
                             status=status, cluster_rows=cluster_rows,
                             ahora_txt=ahora_txt)
    cont["senales"] = senales
    return cont


def _persistir_dia(con, d, cont, evaluaciones, emos, *, status="confirmado",
                   cluster_rows=(), ahora_txt=None) -> int:
    """Fase BD del día. UPDATE-only de z_r (M7); signals con persistencia
    ESTABLE por clave natural (day,target_type,target_id,metric) — CC-T1-1
    (D-047): UPDATE conservando signals.id si la clave ya existe, INSERT si
    no; las viejas del día que ya no son señal se BORRAN solo si NO están
    referenciadas por alert_log (FK); las referenciadas quedan
    status='descartado' (soft-delete, dominio del schema). 'reactivo' se
    preserva siempre (D-042). 10 claves detecta.* con ts del DÍA ANALÍTICO
    (informe_datos filtra ops_metrics por fecha). Todo en UNA tx."""
    senales = 0
    with db.tx(con):
        for item, ev, _alerta in evaluaciones:
            if ev.z_r is None:
                continue  # día ciego: NO se escribe; z_r queda como estaba
            cur = con.execute(
                "UPDATE term_stats SET z_r = ? WHERE day = ? AND term_id = ?",
                (float(ev.z_r), d, item["term_id"]))  # float(Decimal), M1/trampa 10
            if cur.rowcount != 1:
                raise DetectaError(
                    f"z_r sin fila destino: term_id={item['term_id']} día {d}")
            cont["zr_escritos"] += 1
        ahora = ahora_txt or db.now_iso()
        nuevas: list = []
        for item, ev, alerta in evaluaciones:
            if alerta:
                nuevas.append((item["tipo"], item["term_id"], ev))
        for item, ev, alerta in emos:
            if alerta:  # alta idempotente de emocion:{lang} (trampa 8)
                tid = _alta_term(con, f"emocion:{item['lang']}", "emocion")
                nuevas.append(("emocion", tid, ev))
        nuevas.extend(("cluster", cid, ev) for cid, ev in cluster_rows)
        viejas = {(r["target_type"], r["target_id"], r["metric"]): r["id"]
                  for r in con.execute(
                      "SELECT id, target_type, target_id, metric FROM signals"
                      " WHERE day = ? AND status != 'reactivo'", (d,))}
        for target_type, target_id, ev in nuevas:
            for metrica, valor in (("z_r", ev.z_r), ("cusum", ev.s_cusum),
                                   ("mk", ev.p_mk)):
                if valor is None:
                    continue  # métrica no computable: sin fila, jamás NULL/0
                clave = (target_type, target_id, metrica)
                sid = viejas.pop(clave, None)
                if sid is None:
                    con.execute(
                        "INSERT INTO signals(day, target_type, target_id, metric,"
                        " score, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (d, target_type, target_id, metrica, float(valor), status,
                         ahora))
                else:  # UPSERT por clave natural: signals.id se CONSERVA (FK)
                    con.execute(
                        "UPDATE signals SET score = ?, status = ?, created_at = ?"
                        " WHERE id = ?", (float(valor), status, ahora, sid))
                senales += 1
        if viejas:  # obsoletas del día: DELETE solo si nadie las referencia
            referenciadas = {r[0] for r in con.execute(
                "SELECT DISTINCT signal_id FROM alert_log"
                " WHERE signal_id IS NOT NULL")}
            for sid in viejas.values():
                if sid in referenciadas:
                    con.execute("UPDATE signals SET status = 'descartado'"
                                " WHERE id = ?", (sid,))
                else:
                    con.execute("DELETE FROM signals WHERE id = ?", (sid,))
        ts = f"{d}T23:59:59Z"   # día analítico, NUNCA el reloj anfitrión (D-047)
        for clave in CLAVES_METRICAS:
            con.execute("INSERT INTO ops_metrics(ts, clave, valor) VALUES (?, ?, ?)",
                        (ts, f"detecta.{clave}", float(cont.get(clave, 0))))
    return senales


def ejecutar(cfg, con, *, desde=None, hasta=None, dia=None, todo=False,
             ahora=None, motor=None, series=None) -> dict:
    """Una ejecución de detecta sobre un rango de días (ASC, determinista).
    `ahora` inyectable (date o callable → date) para congelar 'ayer' en tests.
    Devuelve contadores, avisos e infos por día para el CLI."""
    motor, series = _capa(motor, series)
    ahora_txt = None
    if isinstance(ahora, datetime):  # D-047: created_at de la corrida simulada
        ahora_txt = ahora.strftime("%Y-%m-%dT%H:%M:%SZ")
        ahora = ahora.date()
    hoy = ahora() if callable(ahora) else ahora
    if hoy is None:
        hoy = _fecha(db.now_iso()[:10])
    ayer = (hoy - timedelta(days=1)).isoformat()
    primero = primer_dia_stats(con)
    avisos: list = []
    infos: list = []
    if primero is None:  # primer día de la vida del sistema
        return {"dias": [], "avisos": avisos, "infos": infos, "senales": 0,
                "alertas": 0, "inmaduras": 0, "sin_datos": True}
    if todo:
        ini, fin = primero, hasta or ayer
    elif dia is not None:
        ini = fin = dia
    elif desde is not None:
        ini, fin = desde, hasta or ayer
    else:
        ini = fin = ayer
    # Avisos de rango E3 (simétricos)
    ultimo_signals = con.execute("SELECT MAX(day) FROM signals").fetchone()[0]
    if ultimo_signals and ini <= ultimo_signals:
        # Sugerir el día SIGUIENTE al último evaluado, no re-evaluarlo (M4a)
        retomar = (_fecha(ultimo_signals) + timedelta(days=1)).isoformat()
        avisos.append(f"re-ejecutando días ya evaluados: considera "
                      f"--desde {retomar} --hasta {hoy.isoformat()}")
    if ini < primero:
        infos.append(f"sin stats antes de {primero}: se empieza ahí")
        ini = primero
    if fin < ini:
        return {"dias": [], "avisos": avisos, "infos": infos, "senales": 0,
                "alertas": 0, "inmaduras": 0, "sin_datos": False}
    dias = _dias_calendario(ini, fin)
    infos.append(f"detecta: evaluando {len(dias)} días ({ini} … {fin})")
    resultados = []
    senales = alertas = inmaduras = 0
    for i, d in enumerate(dias, 1):
        historia = (_fecha(d) - _fecha(primero)).days
        try:
            cont = detectar_dia(con, d, motor=motor, series=series,
                                historia=historia, ahora_txt=ahora_txt)
        except (sqlite3.Error, DetectaError) as e:
            raise DetectaError(f"día {d}: {e}") from e
        if cont["dia_hueco"]:
            avisos.append(f"{d}: día hueco (0 documentos); no se evalúa")
        elif cont["dia_sin_procesar"]:
            avisos.append(f"{d}: día sin procesar: ejecuta 'sibila procesa' antes")
        elif cont["dia_parcial"]:
            avisos.append(f"{d}: día parcial (<50 % de la mediana 28 d); vetado "
                          "como objetivo, entra en baselines futuras")
        elif cont["mes_inmaduro"]:
            avisos.append(f"{d}: mes inmaduro (historia {historia} días < 28): "
                          "alertas como 'inmaduro'")
        if cont["dias_evaluados"]:
            infos.append(f"{d}: {cont['alertas']} alertas "
                         f"({cont['alertas_inmaduras']} inmaduras), "
                         f"{cont['elegibles']} elegibles, "
                         f"{cont['items_ciego']} ítems ciegos")
        senales += cont.get("senales", 0)
        alertas += cont["alertas"]
        inmaduras += cont["alertas_inmaduras"]
        resultados.append((d, cont))
        if i % 30 == 0:  # trampa 11: progreso en rangos enormes
            log.info("detecta: %d/%d días evaluados", i, len(dias))
    return {"dias": resultados, "avisos": avisos, "infos": infos,
            "senales": senales, "alertas": alertas, "inmaduras": inmaduras,
            "sin_datos": False}

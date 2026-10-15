"""Capa de datos del informe semanal (`sibila informe`, Bloque 7).

SIEMPRE mode=ro (URI + timeout=30, espejo EXACTO de resumen.py, D-B7): el
informe NO escribe NADA en la BD — ni siquiera ops_metrics (TP-N4: reproducible
= recomputado). El único artefacto es el FICHERO (tmp + os.replace, trampa 14)
y su `.meta.json` hermano (A-B7-1: la trazabilidad vive FUERA del render
byte-exacto).

Defensas estructurales:
- NINGUNA consulta selecciona author_hash (spec §6.8/§9): ni llega a memoria.
- emo_stats.valence NULL (residual R1 de D-042) → se entrega None → "n/d"
  (TP-N12; la pura jamás recibe 0,0 % falso, trampa 4).
- GDELT vacío → gdelt=None → "n/d"; la escritura de gdelt_ref es otra
  subacción (`--actualizar-gdelt`, gdelt.py), NUNCA en esta ejecución (M3).
- La lógica de secciones/render es de la capa pura (`sibila/informe/`): yo
  solo extraigo filas y monto DatosInforme (contrato §5 + D-T7-5…8).

DESVIACIONES registradas (decisión de consolidación):
1. Nombre `informe_datos.py` y no `informe.py`: el paquete puro entregado
   (`sibila/informe/`) sombrearía al módulo plano del mismo nombre. Patrón
   análogo a detecta.py/deteccion/.
2. Emoción fuera del informe: el DatosInforme real congelado no tiene campo
   emoción; esta extracción NO lee emo_stats (TP-N12 cubierto vía gdelt=n/d).
3. (RESUELTA en T2, §6.1) json/csv activados con sus vectores congelados.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path

from . import SibilaError

log = logging.getLogger("sibila.informe")

TIMEOUT_S = 30                      # espejo resumen.py (busy por conexión)
TOP_TENSION = 10                    # sube/baja: top por |z_r| del período
FORMATOS = ("md", "json", "csv")   # §6.1 T2: vectores congelados ya existen


class InformeError(SibilaError):
    """Fallo previsto del informe (BD ilegible, rango inválido, disco)."""


def conectar_ro(db_path: Path) -> sqlite3.Connection:
    """Conexión SOLO LECTURA (trampa 1: inmunidad de concurrencia por
    construcción). as_uri() escapa # ? % y espacios (lección Dijkstra B2)."""
    try:
        con = sqlite3.connect(Path(db_path).as_uri() + "?mode=ro",
                              uri=True, timeout=TIMEOUT_S)
    except sqlite3.Error as e:
        raise InformeError(f"no se pudo abrir la base en solo-lectura: {e}") from e
    con.row_factory = sqlite3.Row
    return con


def _capa(capa=None):
    """Capa pura del informe (contrato §5/D-T7): DatosInforme, render_informe
    (+ render_csv/render_json si la edición los separa), alertas_fmt de
    sibila/alertas. Inyectable en tests."""
    if capa is not None:
        return capa
    from types import SimpleNamespace
    from .informe import render as _r
    from .alertas import reglas as _reg
    return SimpleNamespace(
        DatosInforme=_r.DatosInforme,
        render_informe=_r.render_informe,
        render_csv=_r.render_csv,
        render_json=_r.render_json,
        alertas_fmt=_reg.alertas_fmt,
        INFORME_VERSION=getattr(_r, "INFORME_VERSION", "desconocida"),
    )


def _fuentes(cfg) -> "tuple[int | None, list[str]]":
    """(fuentes_total, nombres habilitadas) desde fuentes.toml (M2: el vector
    exige "3/4"); ausente/ilegible → (None, []) = degradado visible, nunca 0."""
    candidatas = [Path(cfg.data_dir) / "fuentes.toml",
                  Path(cfg.data_dir).parent / "fuentes.toml"]
    for ruta in candidatas:
        if ruta.exists():
            try:
                with ruta.open("rb") as f:
                    datos = tomllib.load(f)
            except (OSError, tomllib.TOMLDecodeError):
                return None, []
            hab = [n for n, c in datos.items()
                   if isinstance(c, dict) and c.get("habilitada", True)]
            return len(hab), hab
    return None, []


def _conteos(con, desde: str, hasta: str) -> dict:
    r = con.execute(
        "SELECT COUNT(*),"
        " SUM(CASE WHEN duplicate_of IS NOT NULL THEN 1 ELSE 0 END),"
        " COUNT(DISTINCT source_id) FROM documents WHERE dia BETWEEN ? AND ?",
        (desde, hasta)).fetchone()
    # excluidos por fecha: dia es NULL por construcción (procesa) → el período
    # se mide por fetched_at (día de captura), nunca por dia
    excl = con.execute(
        "SELECT COUNT(*) FROM documents WHERE published_at_real = 0"
        " AND substr(fetched_at, 1, 10) BETWEEN ? AND ?", (desde, hasta)).fetchone()[0]
    return {"docs": r[0], "dups": r[1] or 0, "excl_fecha": excl,
            "fuentes_on": r[2] or 0}


def _metricas_dias(con, desde: str, hasta: str) -> dict:
    """Contadores detecta.* del período (ops_metrics lleva ts, no day)."""
    out = {"elegibles": 0, "ciegos": 0, "parcial": False, "hueco": False,
           "inmaduro": False}
    claves = {"detecta.elegibles": "elegibles", "detecta.items_ciego": "ciegos"}
    for clave, destino in claves.items():
        r = con.execute(
            "SELECT SUM(valor) FROM ops_metrics WHERE clave = ?"
            " AND substr(ts, 1, 10) BETWEEN ? AND ?", (clave, desde, hasta)).fetchone()
        out[destino] = int(r[0] or 0)
    for clave, destino in (("detecta.dia_parcial", "parcial"),
                           ("detecta.dia_hueco", "hueco"),
                           ("detecta.mes_inmaduro", "inmaduro")):
        r = con.execute(
            "SELECT SUM(valor) FROM ops_metrics WHERE clave = ?"
            " AND substr(ts, 1, 10) BETWEEN ? AND ?", (clave, desde, hasta)).fetchone()
        out[destino] = bool(r[0])
    return out


def _tension(con, desde: str, hasta: str) -> "tuple[tuple, tuple]":
    """sube/baja: (etiqueta, z_r string 4dec) crudo — el render ORDENA (D-T7-5).
    Los clústeres se etiquetan 'cluster:{hex16}' (D-T7-7: mapear_tema espera
    ese prefijo; sin él salía el hex crudo de 64 chars ilegible — rev.
    Dijkstra M7)."""
    filas = con.execute(
        "SELECT t.text, t.type, ts.z_r FROM term_stats ts"
        " JOIN terms t ON t.id = ts.term_id"
        " WHERE ts.day BETWEEN ? AND ? AND ts.z_r IS NOT NULL"
        " ORDER BY ts.day, t.text", (desde, hasta)).fetchall()
    por_term: dict = {}
    for f in filas:  # el z_r del ÚLTIMO día del período (tensión actual)
        tema = (f"cluster:{f['text'][:16]}" if f["type"] == "cluster"
                else f["text"])
        por_term[tema] = f["z_r"]
    items = sorted(por_term.items(), key=lambda kv: abs(kv[1]), reverse=True)
    sube = tuple((t, f"{z:.4f}") for t, z in items if z > 0)[:TOP_TENSION]
    baja = tuple((t, f"{z:.4f}") for t, z in items if z < 0)[:TOP_TENSION]
    return sube, baja


def _emergentes(con, desde: str, hasta: str) -> tuple:
    """Términos cuyo PRIMER día con stats cae en el período (nuevos)."""
    return tuple(r[0] for r in con.execute(
        "SELECT t.text FROM terms t JOIN term_stats ts ON ts.term_id = t.id"
        " WHERE t.type = 'term' GROUP BY t.text"
        " HAVING MIN(ts.day) BETWEEN ? AND ? ORDER BY t.text", (desde, hasta)))


def _alertas(con, desde: str, hasta: str, capa, etiquetas: dict) -> tuple:
    """Líneas formateadas por alertas_fmt (misma función pura que la alerta,
    D-T7-8: formato único). Una por (target, día) del período. El NIVEL
    mostrado es el que se notificó de verdad (último alert_log de esa señal;
    D-T7-2 en práctica) — nunca una reclasificación improvisada; si la señal
    nunca se envió (cooldown/previa a alerta), se marca 'alerta' (fallback
    documentado, sin inventar severidad)."""
    filas = con.execute(
        "SELECT s.day, s.target_type, s.target_id, s.metric, s.score, s.status,"
        " t.text FROM signals s JOIN terms t ON t.id = s.target_id"
        " WHERE s.day BETWEEN ? AND ? AND s.status IN ('confirmado', 'inmaduro')"
        " ORDER BY s.day, t.text, s.metric",   # 'descartado' fuera (CC-T1-1)
        (desde, hasta)).fetchall()
    # nivel notificado por (day, target_id): último envío real en alert_log
    niveles: dict = {}
    for r in con.execute(
            "SELECT s.day, s.target_id, l.nivel, l.sent_at FROM alert_log l"
            " JOIN signals s ON s.id = l.signal_id"
            " WHERE l.canal NOT LIKE 'fallo:%'"
            " ORDER BY l.sent_at ASC, l.rowid ASC"):
        niveles[(r["day"], r["target_id"])] = r["nivel"]
    por_target: dict = {}
    for f in filas:
        por_target.setdefault((f["day"], f["target_id"], f["text"],
                               f["target_type"], f["status"]), {})[f["metric"]] = f["score"]
    lineas = []
    for (dia, tid, texto, ttype, status), m in sorted(por_target.items()):
        senal = {"tema": texto, "target_type": ttype, "status": status, "day": dia}
        nivel = niveles.get((dia, tid), "alerta")
        lineas.append(capa.alertas_fmt(senal, nivel, etiquetas,
                                       z_r=m.get("z_r"), p_mk=m.get("mk"),
                                       s_cusum=m.get("cusum")))
    return tuple(lineas)


def _anomalias(con, desde: str, hasta: str, gdelt, metr: dict) -> tuple:
    """Anomalías del período (D-T7-5): GDELT parcial y los días anómalos del
    pipeline (parcial/hueco/ítems ciegos, desde ops_metrics de detecta —
    rev. Dijkstra M3; con B1 los ciegos ya son el dato real)."""
    out = []
    if gdelt is not None and 0 < gdelt[1] < 100:
        out.append(f"GDELT parcial: {gdelt[1]} titulares (<100)")
    if metr["parcial"]:
        out.append("dia parcial detectado en el periodo (gate detecta)")
    if metr["hueco"]:
        out.append("dia hueco detectado en el periodo (sin corpus)")
    # Los ítems ciegos NO llevan línea aquí: el vector (i) congelado tiene
    # ciegos=2 con anomalias=() (ya son visibles en §1 cobertura; añadirles
    # línea rompería los vectores byte-exactos f706081a/13a45d3e/beb32a52)
    return tuple(out)


def _predicciones(con) -> dict:
    """Tracker desde la TABLA predictions (D-044: nunca el JSONL)."""
    r = con.execute(
        "SELECT COUNT(*), SUM(CASE WHEN madura = 0 THEN 1 ELSE 0 END),"
        " SUM(CASE WHEN estado != 'pendiente' THEN 1 ELSE 0 END)"
        " FROM predictions").fetchone()
    return {"pend": r[0] or 0, "pend_inm": r[1] or 0, "resueltas": r[2] or 0}


def _gdelt(con, desde: str, hasta: str):
    """(tema, n) de referencia GDELT del período; SIN fila → None → n/d (TP-N12)."""
    r = con.execute(
        "SELECT tema, n FROM gdelt_ref WHERE day BETWEEN ? AND ?"
        " ORDER BY day DESC, tema LIMIT 1", (desde, hasta)).fetchone()
    return (r["tema"], r["n"]) if r else None


def _etiquetas_cluster(con, desde: str, hasta: str) -> dict:
    """cluster:{hex16} → texto del miembro etiqueta (mayor df del día, A-B6-7).
    La pertenencia no es invertible desde cluster_key: se recomputa la
    clusterización del día vía detecta (misma entrada determinista que procesa).
    Hex sin etiqueta → no se mapea: la pura lo muestra crudo y lo anota (D-T7-7)."""
    from . import detecta
    dias = [r[0] for r in con.execute(
        "SELECT DISTINCT s.day FROM signals s JOIN terms t ON t.id = s.target_id"
        " WHERE t.type = 'cluster' AND s.day BETWEEN ? AND ?", (desde, hasta))]
    mapa: dict = {}
    for d in dias:
        try:
            clusteres = detecta._clusteres_del_dia(con, d)
        except Exception as e:  # degradado visible: hex crudo, nunca crash
            log.warning("etiquetas de clúster del día %s no resueltas: %s", d, e)
            continue
        for _mid, (cid, miembros) in clusteres.items():
            if cid in mapa:
                continue
            fila = con.execute(
                "SELECT t.text, ts.df FROM term_stats ts"
                " JOIN terms t ON t.id = ts.term_id"
                " WHERE ts.day = ? AND ts.term_id IN (%s)"
                " ORDER BY ts.df DESC, t.text ASC LIMIT 1"
                % ",".join("?" * len(miembros)), (d, *miembros)).fetchone()
            clave = con.execute("SELECT cluster_key FROM terms WHERE id = ?",
                                (cid,)).fetchone()
            if fila and clave:
                mapa[f"cluster:{clave[0][:16]}"] = fila["text"]
    return mapa


def ejecutar(cfg, con_ro, *, desde: str, hasta: str, ahora=None, capa=None,
             formato: str = "md") -> dict:
    """Monta DatosInforme desde la conexión RO y renderiza. NO escribe en BD.
    Devuelve {contenido (str|bytes), meta, n_alertas, n_predicciones}."""
    capa = _capa(capa)
    ahora = ahora or datetime.now()  # solo para .meta.json; el render es puro
    if formato not in FORMATOS:
        raise InformeError(f"formato {formato!r} no soportado (md, json, csv)")
    fuentes_total, _hab = _fuentes(cfg)
    conteos = _conteos(con_ro, desde, hasta)
    metr = _metricas_dias(con_ro, desde, hasta)
    sube, baja = _tension(con_ro, desde, hasta)
    etiquetas = _etiquetas_cluster(con_ro, desde, hasta)
    alertas = _alertas(con_ro, desde, hasta, capa, etiquetas)
    gdelt = _gdelt(con_ro, desde, hasta)
    preds = _predicciones(con_ro)
    anomalias = _anomalias(con_ro, desde, hasta, gdelt, metr)
    gdelt_txt = "n/d" if gdelt is None else f"{gdelt[1]} titulares ({gdelt[0]})"
    dia_txt = desde if desde == hasta else f"{desde}..{hasta}"
    campos = dict(dia=dia_txt, docs=conteos["docs"],
                  fuentes_on=conteos["fuentes_on"],
                  # M4: ausente/ilegible → "n/d" (degradado visible, nunca 0)
                  fuentes_total=fuentes_total if fuentes_total is not None else "n/d",
                  dups=conteos["dups"], excl_fecha=conteos["excl_fecha"],
                  elegibles=metr["elegibles"], ciegos=metr["ciegos"],
                  parcial=metr["parcial"], hueco=metr["hueco"],
                  inmaduro=metr["inmaduro"], sube=sube, baja=baja,
                  emergentes=_emergentes(con_ro, desde, hasta),
                  alertas=alertas, anomalias=anomalias,
                  pend=preds["pend"], pend_inm=preds["pend_inm"],
                  resueltas=preds["resueltas"], gdelt=gdelt_txt,
                  etiquetas=etiquetas)
    try:
        datos = capa.DatosInforme(**campos)
        render = {"md": capa.render_informe, "json": capa.render_json,
                  "csv": capa.render_csv}[formato]
        contenido = render(datos)   # str (md) o BYTES (json/csv): propagar tal cual
    except (AttributeError, TypeError, ValueError) as e:
        raise InformeError(f"la capa pura rechazó los datos del informe: {e}") from e
    meta = {"renderer": getattr(capa, "INFORME_VERSION", "desconocida"),
            "ahora": ahora.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(ahora, datetime)
                     else str(ahora),
            "rango": [desde, hasta], "formato": formato}
    return {"contenido": contenido, "meta": meta, "n_alertas": len(alertas),
            "n_predicciones": preds["pend"], "dia": dia_txt}


def escribir_fichero(ruta: Path, contenido, meta: dict) -> None:
    """Escritura ATÓMICA (tmp + os.replace, utf-8 explícito — trampa 14/T8):
    un informe a medias NUNCA queda como definitivo. Metadatos al .meta.json
    hermano (M5: byte-exacto solo se exige al artefacto)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".tmp")
    datos = contenido.encode("utf-8") if isinstance(contenido, str) else contenido
    try:
        tmp.write_bytes(datos)
        os.replace(tmp, ruta)
    except OSError as e:
        try:
            tmp.unlink(missing_ok=True)
        finally:
            raise InformeError(f"no se pudo escribir {ruta}: {e}") from e
    ruta.with_suffix(ruta.suffix + ".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")


def semana_iso(dia: date) -> "tuple[str, str]":
    """(desde, hasta) = lunes..domingo de la semana ISO de `dia` (defecto
    DECIDIDO A-B7-1: semana ISO terminando ayer)."""
    lunes = dia - timedelta(days=dia.weekday())
    return lunes.isoformat(), (lunes + timedelta(days=6)).isoformat()

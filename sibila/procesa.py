"""Capa de datos del procesado (`sibila procesa`): orquestación y persistencia.

ÚNICO módulo del Bloque 4 que toca SQLite (D-B4-01); toda decisión lingüística
vive en sibila/procesado/ (funciones puras). Reglas de oro:
- CPU y carga de modelos FUERA de la tx; dentro solo SQL (D-B4-02).
- UNA tx BEGIN IMMEDIATE por lote: docs + terms + stats + métricas juntos.
- `peso` se RECOMPUTA (jamás multiplicación in situ, D-B4-03).
- Marca de pendiente: calidad_score IS NULL (D-B4-05); NUNCA simhash.
- term_stats se recalcula por día SIN tocar z_r (trampa 3: lo escribe detecta).
- JSON de bot_flags con sort_keys y las 4 claves siempre (trampa 9).
- Un cambio de STOPWORDS_VERSION exige re-procesado completo con --todo
  (no hay columna que lo registra; mismo criterio que BOT_VERSION, D-B4-04).

Limitaciones conocidas registradas:
- El near-dup intra-fuente (simhash) compara contra TODO el histórico de la
  fuente, sin ventana de 28 días (el minhash inter-fuente sí la tiene): coste
  lineal creciente, asumible con el volumen de Fase 1 (rev. Hamilton M5).
- procesa.dias_recalculados agregado de la ejecución puede doble-contar un
  día tocado por 2 lotes (suma por lote, no días distintos); la fila por
  lote es correcta — nota cosmética (rev. Dijkstra M6).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import SibilaError, db
from .procesado import bot_heur, calidad, dedup, emocion, idioma, limpieza, ngramas
from .procesado.stopwords import stopwords

log = logging.getLogger("sibila.procesa")

LOTE_DEFECTO = 200
VENTANA_MINHASH_DIAS = 28          # D-B4-06(b): ventana fija, memoria acotada
MAX_BODY = 1_000_000               # recorte defensivo antes de limpiar (trampa 12)
MAX_HISTORIAL_AUTOR = 500          # published_at por autor para la flag ráfaga

# Las 10 claves ops_metrics por lote (D-B4-10); procesa.dia_parcial es condicional.
CLAVES_METRICAS = ("procesados", "excluidos_fecha", "excluidos_dup", "sin_idioma",
                   "sin_emocion", "near_dup", "republicados", "errores",
                   "dias_recalculados", "modo_degradado")

_AUTO = object()                   # centinela: cargar recursos desde cfg.data_dir


class ProcesaError(SibilaError):
    """Fallo de BD/constraint inesperado (D-B4-11): aborta visible, jamás se salta."""


@dataclass
class ResultadoDoc:
    """Resultado PURO de un doc (fase CPU); la fase BD solo lo vuelca."""
    id: int
    dia: "str | None"
    ok: bool = True
    lang: "str | None" = None
    simhash: "str | None" = None
    duplicate_of: "int | None" = None
    calidad: float = 0.0
    flags_json: "str | None" = None
    peso: float = 1.0
    firma: "tuple | None" = None   # firma minhash (para actualizar el índice tras el commit)


def pendientes(con, bot_version: str, *, dia: "str | None", todo: bool,
               limite: "int | None") -> list:
    """Docs a procesar, ORDER BY id ASC (determinista; el canónico near-dup es
    el id menor, D-B4-06). Marca D-B4-05; --todo ignora la marca (re-ejercicio)."""
    sql = ("SELECT id, source_id, body_text, published_at, published_at_real,"
           " fetched_at, author_hash, dia FROM documents")
    where, params = [], []
    if not todo:
        where.append("(calidad_score IS NULL OR bot_detector_version IS NULL"
                     " OR bot_detector_version != ?)")
        params.append(bot_version)
    if dia is not None:
        where.append("dia = ?")
        params.append(dia)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id ASC"
    if limite is not None:
        sql += f" LIMIT {int(limite)}"  # PRAGMA-style: los LIMIT no admiten bind
    return con.execute(sql, params).fetchall()


def cargar_historial_autores(con, filas) -> dict:
    """{author_hash: [(id, published_at), ...] ASC} de docs con
    published_at_real=1. La comparación id<doc.id se hace por doc (D-B4-06
    exige solo pasado). Límite: las MAX_HISTORIAL_AUTOR entradas MÁS
    RECIENTES por autor (rev. Hamilton M2 / Dijkstra M2: las flags ráfaga/
    regularidad miran el presente; se carga DESC y se invierte a ASC)."""
    autores = {f["author_hash"] for f in filas if f["author_hash"]}
    out: dict = {}
    if not autores:
        return out
    marcas = ",".join("?" for _ in autores)
    q = (f"SELECT id, author_hash, published_at FROM documents"
         f" WHERE author_hash IN ({marcas}) AND published_at_real = 1"
         f" ORDER BY published_at DESC, id DESC")
    for r in con.execute(q, tuple(autores)):
        lst = out.setdefault(r["author_hash"], [])
        if len(lst) < MAX_HISTORIAL_AUTOR:
            lst.append((r["id"], r["published_at"]))
    for lst in out.values():
        lst.reverse()                      # entregar ASC (contrato bot_heur)
    return out


def construir_indice(con, hoy=None) -> "tuple[dedup.IndiceMinHash, dict]":
    """Índice MinHash EN MEMORIA (nada se persiste) con los docs de los últimos
    VENTANA_MINHASH_DIAS días: duplicate_of IS NULL, body no vacío, ≥5 palabras
    (la firma centinela tiene J=1 consigo misma, rev. H6). Determinista.
    Devuelve (índice, {documents.id: source_id}).
    `hoy` (date|str ISO) gobierna la ventana; None = reloj real (D-047)."""
    if hoy is None:
        hoy = date.fromisoformat(db.now_iso()[:10])
    elif isinstance(hoy, str):
        hoy = date.fromisoformat(hoy)
    corte = (hoy - timedelta(days=VENTANA_MINHASH_DIAS)).isoformat()
    indice = dedup.IndiceMinHash()
    fuentes: dict = {}
    q = ("SELECT id, source_id, body_text FROM documents"
         " WHERE dia >= ? AND duplicate_of IS NULL AND body_text IS NOT NULL"
         " ORDER BY id ASC")
    for r in con.execute(q, (corte,)):
        limpio = _limpiar_doc(r["body_text"])
        shs = dedup.shingles(limpio)
        if not shs:  # <5 palabras: NUNCA se inserta (rev. H6)
            continue
        indice.insertar(r["id"], dedup.firma_minhash(shs))
        fuentes[r["id"]] = r["source_id"]
    return indice, fuentes


def _limpiar_doc(body: "str | None") -> str:
    """Recorte defensivo a 1 MB ANTES de limpiar (trampa 12), logueado."""
    body = body or ""
    if len(body) > MAX_BODY:
        log.warning("body recortado a %d caracteres antes de limpiar", MAX_BODY)
        body = body[:MAX_BODY]
    return limpieza.limpiar(body)


def _procesar_doc(fila, detector, lexicos, indice, indice_fuentes, sims_fuente,
                  historial) -> ResultadoDoc:
    """Fase CPU pura de un doc. Lanza solo ante error de programación; la capa
    que la llama convierte lo inesperado en doc venenoso (D-B4-11)."""
    res = ResultadoDoc(id=fila["id"], dia=fila["dia"])
    limpio = _limpiar_doc(fila["body_text"])
    lang, conf = idioma.detectar(detector, limpio)
    res.lang = lang
    sh = dedup.simhash(limpio)
    res.simhash = sh
    # (a) near-dup intra-fuente: hamming ≤3 contra simhash persistidos de la
    # MISMA fuente con id menor; duplicate_of = MIN(id) (determinista).
    if sh is not None:
        candidatos = [i for i, h in sims_fuente.get(fila["source_id"], [])
                      if i < res.id and dedup.hamming(h, sh) <= 3]
        if candidatos:
            res.duplicate_of = min(candidatos)
    # (b) re-publicación inter-fuente por MinHash (solo si no es near-dup ya).
    if res.duplicate_of is None and indice is not None:
        shs = dedup.shingles(limpio)
        if shs:
            res.firma = dedup.firma_minhash(shs)
            cand = [i for i in indice.consultar(res.firma)
                    if i < res.id  # canónico = id menor (determinista, D-B4-06)
                    and indice_fuentes.get(i) != fila["source_id"]]
            if cand:
                res.duplicate_of = min(cand)
    res.calidad = calidad.score(limpio, lang, conf)
    hist = tuple(p for i, p in historial.get(fila["author_hash"], []) if i < res.id)
    ctx = bot_heur.ContextoBot(
        published_at=fila["published_at"], fetched_at=fila["fetched_at"] or "",
        author_hash=fila["author_hash"], texto_limpio=limpio, historial_autor=hist)
    fl = bot_heur.flags(ctx)
    if set(fl) != {"regularidad", "plantilla", "marcador", "rafaga"} or \
            not all(isinstance(v, bool) for v in fl.values()):
        raise ProcesaError(f"bot_flags incompletas para doc {res.id}: {sorted(fl)}")
    res.flags_json = json.dumps(fl, sort_keys=True)   # trampa 9: 4 claves, orden fijo
    res.peso = 1.0 * 0.5 ** sum(1 for v in fl.values() if v)   # RECOMPUTO (D-B4-03)
    res._limpio = limpio  # solo vive en memoria del lote; nunca se persiste aquí
    res._emo = emocion.vector(lexicos, limpio, lang) if lang else None
    res._ng = ngramas.extraer(limpio, lang)
    return res


def _alta_term(con, texto: str, tipo: str, cluster_key: "str | None" = None) -> int:
    """INSERT OR IGNORE + SELECT (id ESTABLE, V2). OR IGNORE también tragaría un
    CHECK roto: si el SELECT no devuelve fila es un BUG visible, no un dup
    (trampa 4, espejo de ingesta)."""
    con.execute("INSERT OR IGNORE INTO terms(text, type, cluster_key) VALUES (?, ?, ?)",
                (texto, tipo, cluster_key))
    fila = con.execute("SELECT id FROM terms WHERE text = ?", (texto,)).fetchone()
    if fila is None:
        raise ProcesaError(
            f"term {texto!r} ignorado sin existir previamente: restricción inesperada")
    return fila["id"]


def _secuencias(limpio: str, lang: "str | None"):
    """(content words con repetición, bigramas con repetición, trigramas con
    repetición) sobre el texto limpio — base de occ (A-7: ocurrencias totales)."""
    palabras = dedup._palabras(limpio)
    sw = stopwords(lang)
    terms = [w for w in palabras if len(w) >= 3 and w not in sw]
    seq = [w for w in palabras if w not in sw]
    big = [" ".join(seq[k:k + 2]) for k in range(len(seq) - 1)]
    tri = [" ".join(seq[k:k + 3]) for k in range(len(seq) - 2)]
    return terms, big, tri


def recalcular_dias(con, dias: set, lexicos, ts: "str | None" = None) -> "tuple[int, list]":
    """Stats = VISTA materializada recomputada por día (D-B4-09), DENTRO de la tx
    del lote. Se relee de BD (nunca de la caché del lote: un día puede tocarse
    en dos lotes, trampa 7). Devuelve (días recalculados, días parciales)."""
    pesos_fuente = {r["id"]: (r["peso"] if r["peso"] is not None else 1.0)
                    for r in con.execute("SELECT id, peso FROM sources")}
    parciales: list = []
    for dia in sorted(dias):
        elegibles = con.execute(
            "SELECT id, source_id, body_text, lang, calidad_score, peso"
            " FROM documents WHERE dia = ? AND duplicate_of IS NULL"
            " AND lang IS NOT NULL ORDER BY id ASC", (dia,)).fetchall()
        # 1-3 · term_stats: df/docs = presencia binaria, occ = ocurrencias totales
        df: dict = {}
        occ: dict = {}
        docs_ng: list = []   # (limpio, lang) para emoción y co-ocurrencias
        sets_docs: list = []  # conjunto de términos por doc (co-ocurrencias)
        for d in elegibles:
            limpio = _limpiar_doc(d["body_text"])
            docs_ng.append((d, limpio))
            terms, big, tri = _secuencias(limpio, d["lang"])
            for tipo, lista in (("term", terms), ("bigram", big), ("trigram", tri)):
                for t in lista:
                    occ[(tipo, t)] = occ.get((tipo, t), 0) + 1
                for t in set(lista):
                    df[(tipo, t)] = df.get((tipo, t), 0) + 1
            sets_docs.append(set(terms))
        ids_term: dict = {}
        for tipo, t in sorted(df, key=lambda k: (k[1], k[0])):  # alfabético (rev. H4)
            ids_term[(tipo, t)] = _alta_term(con, t, tipo)
        for (tipo, t), tid in ids_term.items():
            # UPSERT que NUNCA toca z_r (trampa 3: lo escribe detecta, Bloque 5)
            con.execute(
                "INSERT INTO term_stats(day, term_id, docs, occ, df) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(day, term_id) DO UPDATE SET docs = excluded.docs,"
                " occ = excluded.occ, df = excluded.df",
                (dia, tid, df[(tipo, t)], occ[(tipo, t)], df[(tipo, t)]))
        # 4 · emo_stats: DELETE antes del UPSERT (rev. H2: un re-cálculo con
        # Σw²=0 NO puede dejar viva la fila vieja; n/d jamás 0, trampa 8).
        # SOLO con léxicos cargados (rev. Hamilton N1, bloqueante): en modo
        # degradado (lexicos None) vector() es None para todo y el DELETE
        # BORRARÍA las series de emoción del día; se dejan intactas.
        if lexicos is not None:
            con.execute("DELETE FROM emo_stats WHERE day = ?", (dia,))
            items_lang: dict = {}
            for d, limpio in docs_ng:
                emo = emocion.vector(lexicos, limpio, d["lang"])
                if emo is None:
                    continue
                w = (d["calidad_score"] or 0.0) * (d["peso"] or 0.0) \
                    * pesos_fuente.get(d["source_id"], 1.0)   # D-CONS-1 (A-1)
                items_lang.setdefault(d["lang"], []).append((emo, w))
            for lang in sorted(items_lang):
                agg = emocion.agregar_dia(items_lang[lang])
                if agg is None:
                    continue
                v, a, n, n_eff = agg
                con.execute(
                    "INSERT INTO emo_stats(day, lang, valence_mean, arousal_mean, n, n_efectivo)"
                    " VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(day, lang) DO UPDATE SET valence_mean = excluded.valence_mean,"
                    " arousal_mean = excluded.arousal_mean, n = excluded.n,"
                    " n_efectivo = excluded.n_efectivo",
                    (dia, lang, v, a, n, n_eff))
        # 5 · clústeres del día: identidad estable por cluster_key (D-B4-08)
        df_term = {t: d for (tipo, t), d in df.items() if tipo == "term"}
        cooc: dict = {}
        for s in sets_docs:
            miembros = sorted(t for t in s if df_term.get(t, 0) >= ngramas._DF_MIN)
            for x in range(len(miembros)):
                for y in range(x + 1, len(miembros)):
                    par = (miembros[x], miembros[y])
                    cooc[par] = cooc.get(par, 0) + 1
        stats = ngramas.StatsDia(df=df_term, docs_elegibles=len(elegibles), cooc=cooc)
        for clu in ngramas.clusterizar(stats):
            ids = sorted(ids_term[("term", t)] for t in clu.miembros)
            clave = hashlib.sha256(
                ",".join(str(i) for i in ids).encode("ascii")).hexdigest()
            _alta_term(con, f"cluster:{clave[:16]}", "cluster", clave)
        # 6 · día parcial: se REGISTRA, no se bloquea (D-B4-12; la prohibición
        # de alertar es de detecta, Bloque 5)
        docs_dia = con.execute(
            "SELECT COUNT(*) FROM documents WHERE dia = ?", (dia,)).fetchone()[0]
        prev = [r[0] for r in con.execute(
            "SELECT COUNT(*) FROM documents WHERE dia < ? AND dia >= ? GROUP BY dia",
            (dia, (date.fromisoformat(dia) - timedelta(days=28)).isoformat()))]
        if prev and docs_dia < 0.5 * statistics.median(prev):
            con.execute("INSERT INTO ops_metrics(ts, clave, valor) VALUES (?, ?, 1.0)",
                        (ts or db.now_iso(), "procesa.dia_parcial"))
            parciales.append(dia)
    return len(dias), parciales


def procesar_lote(con, filas, recursos, indice, indice_fuentes, modo_degradado,
                  ts: "str | None" = None) -> dict:
    """Un lote: FASE CPU fuera de tx + FASE BD en UNA tx (D-B4-02).
    recursos = (detector, lexicos). Invariante: len(filas) == procesados + errores."""
    detector, lexicos = recursos
    cont = {k: 0 for k in CLAVES_METRICAS}
    cont["modo_degradado"] = 1 if modo_degradado else 0
    historial = cargar_historial_autores(con, filas)
    # Simhash persistidos por fuente (id ASC); se actualiza en memoria por doc.
    max_id = filas[-1]["id"]
    sims_fuente: dict = {}
    for r in con.execute(
            "SELECT id, source_id, simhash FROM documents"
            " WHERE simhash IS NOT NULL AND id < ? ORDER BY id ASC", (max_id,)):
        sims_fuente.setdefault(r["source_id"], []).append((r["id"], r["simhash"]))
    # FASE CPU (sin tx abierta)
    resultados: list = []
    for fila in filas:
        try:
            res = _procesar_doc(fila, detector, lexicos, indice, indice_fuentes,
                                sims_fuente, historial)
        except Exception as e:  # doc venenoso (D-B4-11): se cuenta, calidad 0.0
            log.warning("doc %d venenoso en procesa: %s", fila["id"], e)
            res = ResultadoDoc(id=fila["id"], dia=fila["dia"], ok=False,
                               lang=None, calidad=0.0)
        resultados.append(res)
        if res.simhash is not None:  # visible para los siguientes docs del lote
            sims_fuente.setdefault(fila["source_id"], []).append((res.id, res.simhash))
    # FASE BD (UNA tx; solo SQL)
    bot_version = bot_heur.BOT_VERSION
    dias_tocados: set = set()
    with db.tx(con):
        for res in resultados:
            con.execute(
                "UPDATE documents SET lang = ?, simhash = ?, duplicate_of = ?,"
                " calidad_score = ?, bot_flags = ?, bot_detector_version = ?, peso = ?"
                " WHERE id = ?",
                (res.lang, res.simhash, res.duplicate_of, res.calidad, res.flags_json,
                 bot_version, res.peso, res.id))
            if not res.ok:
                cont["errores"] += 1
                continue
            cont["procesados"] += 1
            if res.dia is None:
                cont["excluidos_fecha"] += 1
            if res.duplicate_of is not None:
                cont["excluidos_dup"] += 1
            if res.lang is None:
                cont["sin_idioma"] += 1
            if res.dia is not None and res.duplicate_of is None and res.lang is not None:
                if res._emo is None:
                    cont["sin_emocion"] += 1
            if res.duplicate_of is not None and res.simhash is not None and res.firma is None:
                cont["near_dup"] += 1
            elif res.duplicate_of is not None:
                cont["republicados"] += 1
        # terms nuevos del lote EN ORDEN ALFABÉTICO (rev. H4: ids estables)
        nuevos: set = set()
        for res in resultados:
            if res.ok:
                ng = res._ng
                nuevos |= {("term", t) for t in ng.terminos}
                nuevos |= {("bigram", t) for t in ng.bigramas}
                nuevos |= {("trigram", t) for t in ng.trigramas}
        for tipo, t in sorted(nuevos, key=lambda k: (k[1], k[0])):
            _alta_term(con, t, tipo)
        dias_tocados = {res.dia for res in resultados if res.dia is not None}
        n_dias, _parciales = recalcular_dias(con, dias_tocados, lexicos, ts=ts)
        cont["dias_recalculados"] = n_dias
        ts = ts or db.now_iso()
        for clave in CLAVES_METRICAS:
            con.execute("INSERT INTO ops_metrics(ts, clave, valor) VALUES (?, ?, ?)",
                        (ts, f"procesa.{clave}", float(cont[clave])))
    if len(filas) != cont["procesados"] + cont["errores"]:  # invariante T-B2-01
        raise AssertionError(f"contadores rotos en procesa: {cont} vs {len(filas)} filas")
    # Tras COMITEAR el lote: el índice minhash se actualiza en orden id ASC
    # (rev. H3: dos republicaciones de la misma ejecución deben verse).
    if indice is not None:
        for res in sorted(resultados, key=lambda r: r.id):
            if res.ok and res.firma is not None and res.duplicate_of is None:
                indice.insertar(res.id, res.firma)
                indice_fuentes[res.id] = next(
                    f["source_id"] for f in filas if f["id"] == res.id)
    cont["_parciales"] = _parciales
    return cont


def _cargar_recursos(cfg, detector, lexicos):
    """Cargas pesadas UNA vez por ejecución; ausencia = degradado con aviso y
    métrica procesa.modo_degradado (D-B4-10)."""
    avisos: list = []
    recursos_dir = cfg.data_dir / "recursos"
    if detector is _AUTO:
        detector = idioma.cargar_detector(recursos_dir / "lid.176.ftz")
    if detector is None:
        avisos.append("sin modelo de idioma (recursos/lid.176.ftz): "
                      "lang quedará NULL (modo degradado)")
    if lexicos is _AUTO:
        lexicos = emocion.cargar_lexicos({
            "nrc_vad_en": recursos_dir / "nrc_vad_en.txt",
            "nrc_vad_es": recursos_dir / "nrc_vad_es.txt",
            "nrc_emociones_en": recursos_dir / "nrc_emociones_en.txt",
            "nrc_emociones_es": recursos_dir / "nrc_emociones_es.txt"})
    if lexicos is None:
        avisos.append("sin léxicos NRC-VAD: emoción desactivada (modo degradado)")
    return detector, lexicos, avisos


def ejecutar(cfg, con, *, lote: int = LOTE_DEFECTO, dia: "str | None" = None,
             todo: bool = False, limite: "int | None" = None,
             detector=_AUTO, lexicos=_AUTO, hoy=None) -> dict:
    """Una ejecución completa: selección → lotes → resumen. Devuelve contadores
    y avisos para el CLI. Fallo de BD/constraint → ProcesaError (exit 1, D-B4-11)."""
    detector, lexicos, avisos = _cargar_recursos(cfg, detector, lexicos)
    filas = pendientes(con, bot_heur.BOT_VERSION, dia=dia, todo=todo, limite=limite)
    total = {k: 0 for k in CLAVES_METRICAS}
    total["modo_degradado"] = 0
    resumen = {"avisos": avisos, "lotes": [], "dias_parciales": [],
               "pendientes": len(filas), "contadores": total}
    if not filas:
        return resumen
    # D-047: `hoy` (date|str ISO) fija la ventana MinHash y el ts de métricas;
    # sin `hoy`, comportamiento byte-idéntico al de siempre (C-T1-7).
    # rev. D-M2: el contrato admite también datetime (corre inyecta D+1T06:00
    # para otras cosas; aquí manda la FECHA) — normalizar como hace ingesta.
    if isinstance(hoy, datetime):
        hoy = hoy.date()
    elif isinstance(hoy, str):
        hoy = date.fromisoformat(hoy)
    ts_dia = f"{hoy}T23:59:59Z" if hoy is not None else None
    try:
        indice, indice_fuentes = construir_indice(con, hoy=hoy)
    except Exception as e:
        avisos.append(f"sin índice minhash ({e}): re-publicación inter-fuente desactivada")
        indice, indice_fuentes = None, {}
    modo_degradado = detector is None or lexicos is None or indice is None
    for i in range(0, len(filas), lote):
        trozo = filas[i:i + lote]
        try:
            cont = procesar_lote(con, trozo, (detector, lexicos), indice,
                                 indice_fuentes, modo_degradado, ts=ts_dia)
        except (sqlite3.Error, ProcesaError) as e:
            raise ProcesaError(f"lote a partir de id {trozo[0]['id']}: {e}") from e
        for k in CLAVES_METRICAS:
            total[k] += cont[k] if k != "modo_degradado" else 0
        total["modo_degradado"] = cont["modo_degradado"]
        resumen["lotes"].append(
            f"lote id≥{trozo[0]['id']}: {cont['procesados']} procesados, "
            f"{cont['errores']} errores")
        resumen["dias_parciales"].extend(cont["_parciales"])
    for d in resumen["dias_parciales"]:
        avisos.append(f"día parcial {d}: menos del 50 % de la mediana de 28 días")
    return resumen

"""Persistencia de ingesta (spec §4.1/§5/§6.8): del RawDoc a la tabla documents.

Frontera D-B2-07: este módulo NO importa sibila.conectores NUNCA. La validación del
contrato RawDoc es duck-typing (atributos, no clases) y la normalización/hash viven
AQUÍ (§12 de los planes: el conector entrega url y body CRUDOS; no normaliza ni hashea).

Reglas de oro (plan Liskov bloque 2):
- La red NUNCA dentro de la transacción: fetch fuera; validación y hashing (CPU) fuera;
  DENTRO solo INSERTs, cursor y ops_metrics (tx corta, spec §2).
- Documento defectuoso: se salta contando; el lote sobrevive (un doc venenoso no tiene
  derecho de veto sobre 199 buenos — pero una RESTRICCIÓN inesperada sí aborta visible).
- Cursor, documentos y métricas se guardan EN LA MISMA tx: jamás divergen (D-B2-03/06).
- Contadores con invariante: recibidos == nuevos + dup_url + dup_cont + errores (T-B2-01).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import SibilaError, db

log = logging.getLogger("sibila.ingesta")

FUENTES_SEMILLA = (
    ("reddit", "web", "en"),
    ("lobsters", "web", "en"),
    ("mastodon", "fediverso", "multi"),
    # 4chan permanece en la semilla de REGISTRO (integridad referencial de
    # `sources`: sin ella, la fuente no puede darse de alta ni manualmente).
    # Lo retirado de la distribución pública por defecto (D-075, 2026-10-13)
    # es su CONFIGURACIÓN: ya no aparece en fuentes.toml, así que nunca se
    # descarga salvo que el operador la active a mano. El conector sigue
    # disponible y probado (tests/fuentes_test.toml).
    ("4chan", "tablon", "en"),
)

_PARAMS_BASURA = re.compile(r"^(utm_|fbclid$|gclid$)", re.IGNORECASE)


class IngestaError(SibilaError):
    """Fallo de persistencia que NUNCA debe quedar silencioso (p.ej. INSERT OR IGNORE
    ignorado por una restricción que no es el dedup: CHECK, FK — plan Liskov §9.1)."""


# ---------------------------------------------------------------- contrato RawDoc

def es_fecha_valida(dt) -> bool:
    """UTC estricta: tzinfo presente, offset cero, año >= 2000 (centinela de epoch mal
    parseado). Duck-typing: cualquier objeto con tzinfo/utcoffset/year."""
    return (dt is not None and getattr(dt, "tzinfo", None) is not None
            and dt.utcoffset() == timedelta(0) and dt.year >= 2000)


def validar_rawdoc(doc) -> list[str]:
    """Lista de problemas en español (vacía = válido). Duck-typing (D-B2-07).
    url: None o http(s) — el esquema se admite en mayúsculas (normalizar_url pliega;
    rev. Dijkstra M12). body vacío es válido SI hay url (content_hash quedará NULL)."""
    problemas = []
    fuente = getattr(doc, "fuente", None)
    if not isinstance(fuente, str) or not fuente:
        problemas.append("fuente vacía")
    url = getattr(doc, "url", None)
    if url is not None:
        if not isinstance(url, str) or not url.strip().lower().startswith(
                ("http://", "https://")):
            problemas.append(f"url no http(s): {url!r}")
    body = getattr(doc, "body", None)
    if not isinstance(body, str):
        problemas.append("body no es texto")
    elif url is None and not body:
        problemas.append("sin url y sin cuerpo: no hay nada que persistir")
    crudo = getattr(doc, "crudo", None)
    if not isinstance(crudo, str) or not crudo:
        problemas.append("crudo vacío: sin respaldo de hash")
    published_at = getattr(doc, "published_at", None)
    if published_at is not None and not es_fecha_valida(published_at):
        problemas.append(f"published_at no es UTC estricta: {published_at!r}")
    author_raw = getattr(doc, "author_raw", None)
    if author_raw is not None and not isinstance(author_raw, str):
        problemas.append("author_raw no es texto")
    return problemas


# ------------------------------------------------------- normalización y hashing

def normalizar_url(url: str) -> str:
    """Esquema/host en minúsculas, sin fragment, sin utm_*/fbclid/gclid (resto de params,
    ordenados), sin puertos por defecto, '/' final solo si la ruta es la raíz.
    ValueError si no es http(s) con host (plan Liskov §4). urlsplit puede lanzar
    ValueError por sí solo (IPv6 roto) y .port también (puerto fuera de rango):
    AMBOS casos los recoge ingestar como error del documento, fuera de la tx
    (rev. Dijkstra B2: una URL venenosa no puede vetar el lote)."""
    p = urlsplit(url.strip())
    esquema = p.scheme.lower()
    host = (p.hostname or "").lower()
    if esquema not in ("http", "https") or not host:
        raise ValueError(f"no es una URL http(s) con host: {url[:80]!r}")
    puerto = p.port  # ValueError si fuera de rango 0-65535
    netloc = host + (f":{puerto}" if puerto and (esquema, puerto) not in
                     (("http", 80), ("https", 443)) else "")
    ruta = p.path or "/"
    if ruta != "/" and ruta.endswith("/"):
        ruta = ruta.rstrip("/")  # barra final solo en la raíz
    params = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                    if not _PARAMS_BASURA.match(k))
    return urlunsplit((esquema, netloc, ruta, urlencode(params), ""))


def hash_url(url_normalizada: str) -> str:
    """SHA-256 hex(64) con prefijo de espacio 'url:' (los dos espacios jamás colisionan)."""
    return hashlib.sha256(("url:" + url_normalizada).encode("utf-8")).hexdigest()


def hash_documento(fuente: str, crudo: str) -> str:
    """SHA-256 hex(64) con prefijo 'doc:' — para documentos sin URL (mastodon URN, etc.)."""
    return hashlib.sha256(("doc:" + fuente + "\x1f" + crudo).encode("utf-8")).hexdigest()


def _norm_texto(body: str) -> str:
    """NFC + colapso de whitespace, SIN minúsculas ni NFKC (D-B2-03: las variantes de
    mayúsculas son near-dup → simhash en procesado, no hash exacto; rev. Dijkstra M6 —
    el vector congelado d3a1fbdf… lo fija). SOLO para el hash: el body guardado va CRUDO."""
    return " ".join(unicodedata.normalize("NFC", body).split())


def _author_hash(author_raw: str, clave: str) -> str | None:
    """HMAC-SHA256 sobre strip + NFC, SIN minúsculas (la identidad es la de la
    plataforma; case-folding fusionaría cuentas distintas — rev. Dijkstra M5).
    None si el autor queda vacío. La clave JAMÁS se imprime ni loguea."""
    autor = unicodedata.normalize("NFC", author_raw.strip())
    if not autor:
        return None
    return hmac.new(clave.encode("utf-8"), autor.encode("utf-8"),
                    hashlib.sha256).hexdigest()


# ------------------------------------------------------------------- persistencia

def asegurar_fuentes(con: sqlite3.Connection) -> None:
    """Alta idempotente de las fuentes semilla por nombre UNIQUE (semilla SIEMPRE completa)."""
    with db.tx(con):
        for nombre, tipo, idioma in FUENTES_SEMILLA:
            con.execute(
                "INSERT OR IGNORE INTO sources(nombre, tipo, idioma) VALUES (?, ?, ?)",
                (nombre, tipo, idioma))


def _source_id(con: sqlite3.Connection, nombre: str) -> int:
    fila = con.execute("SELECT id FROM sources WHERE nombre = ?", (nombre,)).fetchone()
    if fila is None:  # fuente no semilla: alta explícita, nunca implícita
        raise db.SchemaError(f"fuente '{nombre}' no dada de alta en sources")
    return fila[0]


def leer_cursor(con: sqlite3.Connection, fuente: str) -> str | None:
    fila = con.execute(
        "SELECT cursor FROM conector_cursor WHERE fuente = ?", (fuente,)).fetchone()
    return fila[0] if fila else None


def _guardar_cursor(con: sqlite3.Connection, fuente: str, cursor: str, ahora: str) -> None:
    con.execute(
        "INSERT INTO conector_cursor(fuente, cursor, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(fuente) DO UPDATE SET cursor = excluded.cursor,"
        " updated_at = excluded.updated_at",
        (fuente, cursor, ahora))


def ingestar(cfg, conector, cursor: str | None, con: sqlite3.Connection, *,
             limite: int | None = None, hoy=None) -> dict:
    """Una pasada de un conector: fetch (red FUERA de tx) → valida y hashea (CPU FUERA
    de tx) → persiste en UNA tx (docs + cursor + ops_metrics juntos o nada).
    `limite` recorta los documentos procesados (depuración; se aplica tras el fetch).
    CON limite activo el cursor NO se mueve (rev. Hamilton N1 ronda 2: si se guardara,
    los docs no procesados quedarían marcados como vistos y se perderían PARA SIEMPRE).
    Devuelve {'recibidos','nuevos','dup_url','dup_cont','errores','cursor'}.
    La decisión dup_url/dup_cont es DETERMINISTA: primero url, luego contenido (T-B2-05)."""
    docs, cursor_nuevo = conector.fetch(conector.cfg, cursor)  # red FUERA de tx (T-B2-03)
    if limite is not None:
        docs = docs[:limite]
    # D-047: `hoy` (date|datetime|str) fija fetched_at/cursor/métricas en la
    # corrida simulada; None = reloj real (producción byte-idéntica).
    if hoy is None:
        ahora = db.now_iso()
    elif isinstance(hoy, datetime):
        ahora = hoy.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:  # date o str ISO
        ahora = f"{str(hoy)[:10]}T23:59:59Z" 
    clave_hmac = cfg.secretos.get("hmac_key") if cfg else None
    cont = {"recibidos": len(docs), "nuevos": 0, "dup_url": 0, "dup_cont": 0,
            "errores": 0}

    # Fase 1 (CPU, fuera de tx): validación + hashing de TODOS los docs (plan Liskov §2.2)
    preparados = []
    for doc in docs:
        problemas = validar_rawdoc(doc)
        if problemas:
            cont["errores"] += 1
            # url truncada a 80; JAMÁS author_raw ni body en el log (privacidad)
            log.warning("documento saltado de %s (url %.80s): %s",
                        conector.nombre, getattr(doc, "url", "") or "",
                        "; ".join(problemas))
            continue
        try:
            u_hash = (hash_url(normalizar_url(doc.url)) if doc.url is not None
                      else hash_documento(doc.fuente, doc.crudo))
        except ValueError as e:  # puerto inválido, IPv6 roto… (rev. B2: sin veto de lote)
            cont["errores"] += 1
            log.warning("url innormalizable en %s (%.80s): %s", conector.nombre,
                        doc.url or "", e)
            continue
        norm = _norm_texto(doc.body)
        c_hash = (hashlib.sha256(norm.encode("utf-8")).hexdigest() if norm else None)
        a_hash = (_author_hash(doc.author_raw, clave_hmac)
                  if (clave_hmac and doc.author_raw) else None)
        if doc.published_at is not None:  # UTC estricta (validada arriba)
            pub_txt = doc.published_at.isoformat(timespec="seconds").replace("+00:00", "Z")
            real = 1
            dia = doc.published_at.date().isoformat()  # D-B2-04: fecha UTC del doc
        else:
            pub_txt, real, dia = None, 0, None  # exclusión ESTRUCTURAL de baselines
        preparados.append((u_hash, a_hash, pub_txt, real, dia, doc.lang, doc.body,
                           c_hash))

    # Fase 2 (UNA tx): INSERTs + cursor + ops_metrics (plan Liskov §2.3, D-B2-06)
    with db.tx(con):
        source_id = _source_id(con, conector.nombre)
        for u_hash, a_hash, pub_txt, real, dia, lang, body, c_hash in preparados:
            cur = con.execute(
                "INSERT OR IGNORE INTO documents(source_id, url_hash, author_hash,"
                " published_at, published_at_real, fetched_at, lang, body_text,"
                " content_hash, dia) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source_id, u_hash, a_hash, pub_txt, real, ahora, lang, body, c_hash,
                 dia))
            if cur.rowcount == 1:
                cont["nuevos"] += 1
            elif con.execute("SELECT 1 FROM documents WHERE url_hash = ?",
                             (u_hash,)).fetchone():
                cont["dup_url"] += 1
            elif (c_hash is not None
                  and con.execute("SELECT 1 FROM documents WHERE content_hash = ?",
                                  (c_hash,)).fetchone()):
                cont["dup_cont"] += 1
            else:  # OR IGNORE también silencia CHECK/FK: eso es un BUG visible, no un dup
                raise IngestaError(
                    f"INSERT ignorado sin duplicado url ni contenido en "
                    f"{conector.nombre}: restricción inesperada (revisar schema/datos)")
        if limite is None:  # rev. Hamilton N1: con límite el cursor NO se mueve
            _guardar_cursor(con, conector.nombre, cursor_nuevo, ahora)
        else:
            log.info("limite=%d activo en %s: cursor no actualizado (modo depuración)",
                     limite, conector.nombre)
        for clave, valor in (("nuevos", cont["nuevos"]),
                             ("duplicados_url", cont["dup_url"]),
                             ("duplicados_contenido", cont["dup_cont"]),
                             ("errores", cont["errores"])):
            con.execute("INSERT INTO ops_metrics(ts, clave, valor) VALUES (?, ?, ?)",
                        (ahora, f"ingesta.{clave}.{conector.nombre}", float(valor)))

    total = cont["nuevos"] + cont["dup_url"] + cont["dup_cont"] + cont["errores"]
    if total != cont["recibidos"]:  # invariante T-B2-01: si salta, hay un bug
        raise AssertionError(f"contadores rotos en {conector.nombre}: {cont}")
    # con limite el cursor persistido es el de ENTRADA (no se movió); el resultado lo refleja
    cont["cursor"] = cursor_nuevo if limite is None else cursor
    return cont

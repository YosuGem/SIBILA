"""Única vía de acceso a SQLite (spec §2).

WAL, busy_timeout 30 s, foreign_keys ON, transacciones cortas, escritor único.
PROHIBIDO sqlite3.connect fuera de este módulo (el revisor hará grep).
"""
from __future__ import annotations

import importlib.resources
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import SibilaError

log = logging.getLogger("sibila.db")

SCHEMA_VERSION = 1            # versionado interno del schema (D-B1-01; no es versión de programa, D-019)
BUSY_TIMEOUT_MS = 30000


class SchemaError(SibilaError):
    """Schema ausente, de versión futura o no conforme (mensajes en español)."""


# Manifiesto del schema: fuente única de verdad de verify_schema() (D-B1-05).
# Pares (nombre, TIPO declarado) en orden de columna, tal como los devuelve PRAGMA table_info.
EXPECTED_TABLES: dict[str, list[tuple[str, str]]] = {
    "sources": [("id", "INTEGER"), ("nombre", "TEXT"), ("tipo", "TEXT"), ("idioma", "TEXT"),
                ("stratum", "TEXT"), ("sesgo", "TEXT"), ("peso", "REAL")],
    "documents": [("id", "INTEGER"), ("source_id", "INTEGER"), ("url_hash", "TEXT"),
                  ("author_hash", "TEXT"), ("published_at", "TEXT"), ("published_at_real", "INTEGER"),
                  ("fetched_at", "TEXT"), ("lang", "TEXT"), ("body_text", "TEXT"),
                  ("content_hash", "TEXT"), ("simhash", "TEXT"), ("duplicate_of", "INTEGER"),
                  ("calidad_score", "REAL"), ("bot_flags", "TEXT"), ("bot_detector_version", "TEXT"),
                  ("peso", "REAL"), ("dia", "TEXT")],
    "terms": [("id", "INTEGER"), ("text", "TEXT"), ("type", "TEXT"), ("cluster_key", "TEXT")],
    "term_stats": [("day", "TEXT"), ("term_id", "INTEGER"), ("docs", "INTEGER"),
                   ("occ", "INTEGER"), ("df", "INTEGER"), ("z_r", "REAL")],
    "emo_stats": [("day", "TEXT"), ("lang", "TEXT"), ("valence_mean", "REAL"),
                  ("arousal_mean", "REAL"), ("n", "INTEGER"), ("n_efectivo", "REAL")],
    "signals": [("id", "INTEGER"), ("day", "TEXT"), ("target_type", "TEXT"), ("target_id", "INTEGER"),
                ("metric", "TEXT"), ("score", "REAL"), ("status", "TEXT"), ("created_at", "TEXT")],
    "predictions": [("id", "INTEGER"), ("tema", "TEXT"), ("metrica", "TEXT"), ("umbral", "TEXT"),
                    ("ventana", "TEXT"), ("criterio_acierto", "TEXT"), ("created_at", "TEXT"),
                    ("hash", "TEXT"), ("prev_hash", "TEXT"), ("estado", "TEXT"), ("madura", "INTEGER"),
                    ("resuelta_at", "TEXT"), ("resolucion_ciega", "TEXT")],
    "echo_flags": [("doc_id", "INTEGER"), ("tipo", "TEXT"), ("score", "REAL"),
                   ("detector_version", "TEXT"), ("accion", "TEXT")],
    "alert_log": [("signal_id", "INTEGER"), ("nivel", "TEXT"), ("canal", "TEXT"), ("sent_at", "TEXT")],
    "gdelt_ref": [("tema", "TEXT"), ("day", "TEXT"), ("n", "INTEGER"), ("fetched_at", "TEXT")],
    "ops_metrics": [("ts", "TEXT"), ("clave", "TEXT"), ("valor", "REAL")],
    "conector_cursor": [("fuente", "TEXT"), ("cursor", "TEXT"), ("updated_at", "TEXT")],
}

EXPECTED_PKS = {"sources": "id", "documents": "id", "terms": "id",
                "signals": "id", "predictions": "id", "conector_cursor": "fuente"}

# Literales de dominio que deben aparecer en el DDL normalizado (minúsculas, espacios colapsados).
EXPECTED_LITERALS: dict[str, list[str]] = {
    "sources": ["stratum in ('normal','vidente','control')", "nombre text unique"],
    "documents": ["published_at_real in (0,1)", "length(simhash) = 16", "glob '????-??-??'",
                  "check (published_at_real = 1 or published_at is null)",
                  "url_hash text unique", "content_hash text unique"],
    "terms": ["type in ('term','bigram','trigram','cluster','emocion')", "text text unique"],
    "term_stats": ["unique(day, term_id)", "glob '????-??-??'"],
    "emo_stats": ["unique(day, lang)", "glob '????-??-??'"],
    "signals": ["target_type in ('term','bigram','trigram','cluster','emocion')",
                "metric in ('z_r','cusum','mk')",
                "status in ('nuevo','confirmado','descartado','reactivo','inmaduro')",
                "unique(day, target_type, target_id, metric)", "glob '????-??-??'"],
    "predictions": ["estado in ('pendiente','parcial','cumplida','fallada','expirada')",
                    "madura in (0,1)"],
    "echo_flags": ["tipo in ('sincronia','meme','cita_profecia','bot_ia')",
                   "score >= 0 and score <= 1",
                   "accion in ('peso_025','peso_050','excluir_estrato')", "unique(doc_id, tipo)"],
    "alert_log": ["nivel in ('vigilancia','alerta','alarma')"],
    "gdelt_ref": ["unique(tema, day)", "glob '????-??-??'"],
}

EXPECTED_INDEXES = {
    "idx_documents_dia", "idx_documents_source", "idx_term_stats_day", "idx_term_stats_term",
    "idx_signals_day", "idx_signals_status", "idx_alert_log_signal", "idx_gdelt_ref_day",
    "idx_predictions_estado", "idx_ops_metrics_clave_ts",
}


def _schema_sql() -> str:
    """Encoding EXPLÍCITO siempre (trampa T8: el default en Windows es cp1252)."""
    return importlib.resources.files("sibila").joinpath("schema.sql").read_text(encoding="utf-8")


def connect(db_path) -> sqlite3.Connection:
    """Toda conexión sale con los pragmas fijos EN ESTE ORDEN (D-B1-04: foreign_keys y
    busy_timeout son POR CONEXIÓN — hay que fijarlos en CADA connect)."""
    con = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA foreign_keys = ON")
    modo = con.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if modo != "wal":  # :memory: devuelve 'memory' (verificado): avisar, no fallar
        log.warning("journal_mode=%s (esperado 'wal')", modo)
    con.execute("PRAGMA synchronous = NORMAL")
    return con


def init_db(db_path) -> None:
    """Idempotente POR CONSTRUCCIÓN (todo IF NOT EXISTS) y JAMÁS destructivo (D-B1-02)."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    try:
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise SchemaError(
                f"la base tiene schema v{version} y este programa espera v{SCHEMA_VERSION}; "
                "las migraciones llegan en otro bloque")  # NUNCA rebajar ni recrear
        try:
            con.executescript(_schema_sql())  # no-op si ya existe
        except sqlite3.Error as e:
            # rev. M3: base preexistente mal formada (p.ej. índice sobre columna ausente):
            # diagnóstico en español, nunca OperationalError cruda en inglés
            raise SchemaError(
                f"la base existente no es conforme a schema v1 y no pudo repararse: {e}") from e
        if version == 0:
            # Los PRAGMA no admiten bind params: literal entero de la constante (trampa T12)
            con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        # Autodiagnóstico (rev. M3): si la base preexistente está mal formada, que lo diga
        # en español el SchemaError y no un OperationalError crudo en inglés
        problemas = verify_schema(con)
        if problemas:
            raise SchemaError(
                "la base existente no es conforme a schema v1: " + "; ".join(problemas))
    finally:
        con.close()


@contextmanager
def tx(conn: sqlite3.Connection):
    """Transacción corta con BEGIN IMMEDIATE (lock de escritura al entrar: con busy_timeout
    evita el 'database is locked' por upgrade lectura→escritura; base de TP-N10, D-B1-03).
    Nada de red ni cómputo largo dentro (spec §2)."""
    if conn.in_transaction:
        raise RuntimeError("transacciones anidadas no soportadas en este bloque")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:  # también KeyboardInterrupt/SystemExit: la conexión NO queda envenenada (rev. B2)
        conn.execute("ROLLBACK")
        raise
    try:
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")  # si COMMIT falla, intentar deshacer antes de relanzar
        raise


def verify_schema(conn: sqlite3.Connection) -> list[str]:
    """Lista de problemas en español contra el manifiesto; vacía = OK (capa estructural,
    D-B1-05; la verdad de los dominios son los inserts buenos/malos de los tests)."""
    problemas: list[str] = []
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        problemas.append(f"user_version={version}, esperado {SCHEMA_VERSION}")
    tablas = {f[0] for f in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    for t in sorted(set(EXPECTED_TABLES) - tablas):
        problemas.append(f"falta la tabla {t}")
    for t in sorted(tablas - set(EXPECTED_TABLES)):
        problemas.append(f"tabla inesperada {t}")
    for tabla, columnas in EXPECTED_TABLES.items():
        if tabla not in tablas:
            continue
        info = conn.execute(f"PRAGMA table_info({tabla})").fetchall()
        pares = [(f[1], f[2].upper()) for f in info]
        if pares != columnas:
            problemas.append(
                f"columnas de {tabla} no conformes: {[n for n, _ in pares]}")
        pk = EXPECTED_PKS.get(tabla)
        if pk and not any(f[1] == pk and f[5] for f in info):
            problemas.append(f"{tabla}: falta PRIMARY KEY en {pk}")
        fila = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tabla,)).fetchone()
        norm = " ".join((fila[0] or "").lower().split())
        for lit in EXPECTED_LITERALS.get(tabla, []):
            if lit not in norm:
                problemas.append(f"{tabla}: falta el literal de dominio {lit!r}")
    indices = {f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    for idx in sorted(EXPECTED_INDEXES - indices):
        problemas.append(f"falta el índice {idx}")
    return problemas


def integrity_ok(conn: sqlite3.Connection) -> bool:
    return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def now_iso() -> str:
    """ÚNICO punto del paquete donde se estampa la hora (trampa T2).
    Formato congelado YYYY-MM-DDTHH:MM:SSZ (spec §8); prohibido datetime.now() naive."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

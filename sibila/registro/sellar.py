"""sellado puro: construcción y hash de líneas de la cadena (spec §8).

Cadena SHA-256 EN MEMORIA (sin disco: eso es de la capa de datos). Formato
congelado: 7 campos + hash; TODO número es str decimal (D-T6-1: un float
suelto cambia el hash → se RECHAZA con ValueError, sin coerción silenciosa —
T-B6-3). `created_at` NUNCA sale de un reloj: entra como parámetro (T-B6-13).
"""
import hashlib
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from .canonico import canonical_json

GENESIS = "0" * 64          # D-T6-5: prev_hash de la primera línea

CAMPOS = ("created_at", "criterio_acierto", "metrica", "prev_hash",
          "tema", "umbral", "ventana")   # los 7 campos congelados (spec §4.3)

METRICAS = frozenset({"z_r", "cusum", "mk"})

_RE_VENTANA = re.compile(r"^P([1-9][0-9]*)([DW])$")   # D-T6-2 (R5)
_RE_CREATED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")  # D-T6-3
_RE_HASH = re.compile(r"^[0-9a-f]{64}$")               # D-T6-5


def parsear_ventana(ventana: str) -> timedelta:
    """ISO-8601 subconjunto congelado: P[n]D / P[n]W con n entero >0 sin ceros
    a la izquierda ("P07D" inválido por construcción — rev. cruzada N1).
    ValueError ante cualquier otra forma ("7 días", "P0D", "PT1H", "P7d")."""
    m = _RE_VENTANA.match(ventana) if isinstance(ventana, str) else None
    if not m:
        raise ValueError(f"ventana inválida: {ventana!r}")
    n = int(m.group(1))
    return timedelta(days=n) if m.group(2) == "D" else timedelta(weeks=n)


def validar_created_at(created_at: str) -> None:
    """`YYYY-MM-DDTHH:MM:SSZ` exacto (regex) Y fecha/hora reales válidas
    (T-B6-8: "2026-13-01T00:00:00Z" pasa el regex pero no el parseo).
    ValueError si no cumple."""
    if not isinstance(created_at, str) or not _RE_CREATED.match(created_at):
        raise ValueError(f"created_at inválido: {created_at!r}")
    d, h = created_at.split("T")
    date.fromisoformat(d)                      # ValueError si fecha imposible
    hh, mm, ss = (int(x) for x in h[:-1].split(":"))
    if not (0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60):
        raise ValueError(f"created_at inválido: {created_at!r}")


def _es_numero_string(x) -> bool:
    """D-T6-1: str parseable como Decimal (los floats se rechazan, no se
    coercionan — T-B6-3)."""
    if not isinstance(x, str):
        return False
    try:
        Decimal(x)
        return True
    except InvalidOperation:
        return False


def hash_linea(linea_sin_hash: dict) -> str:
    """SHA-256 hex de canonical_json de los 7 campos. ValueError si trae
    clave `hash`, le falta alguno de los 7, tiene claves de más (T-B6-14) o
    algún valor no es str (D-T6-1). No reordena a mano: el orden canónico lo
    da sort_keys."""
    if not isinstance(linea_sin_hash, dict):
        raise ValueError("la línea debe ser un dict")
    if "hash" in linea_sin_hash:
        raise ValueError("hash_linea recibe la línea SIN hash")
    if set(linea_sin_hash) != set(CAMPOS):
        raise ValueError("la línea debe tener exactamente los 7 campos")
    for k in CAMPOS:
        if not isinstance(linea_sin_hash[k], str):
            raise ValueError(f"campo no-string: {k} (D-T6-1)")
    return hashlib.sha256(canonical_json(linea_sin_hash)).hexdigest()


def construir_linea(b, created_at: str, prev_hash: str) -> dict:
    """BorradorPrediccion + created_at + prev_hash → línea de 8 campos con su
    hash encadenado. Valida: ventana (D-T6-2), metrica ∈ METRICAS, umbral
    número-string (D-T6-1), tema y criterio no vacíos, created_at (D-T6-3),
    prev_hash 64 hex minúsculas (D-T6-5). ValueError ante tipo/forma
    incumplida. NUNCA llama a now(): created_at es parámetro."""
    parsear_ventana(b.ventana)
    if b.metrica not in METRICAS:
        raise ValueError(f"metrica desconocida: {b.metrica!r}")
    if not _es_numero_string(b.umbral):
        raise ValueError(f"umbral no es número-string: {b.umbral!r}")
    if not isinstance(b.tema, str) or not b.tema:
        raise ValueError("tema vacío")
    if not isinstance(b.criterio_acierto, str) or not b.criterio_acierto:
        raise ValueError("criterio_acierto vacío")
    validar_created_at(created_at)
    if not isinstance(prev_hash, str) or not _RE_HASH.match(prev_hash):
        raise ValueError(f"prev_hash debe ser 64 hex minúsculas: {prev_hash!r}")
    linea = {"created_at": created_at, "criterio_acierto": b.criterio_acierto,
             "metrica": b.metrica, "prev_hash": prev_hash, "tema": b.tema,
             "umbral": b.umbral, "ventana": b.ventana}
    linea["hash"] = hash_linea(linea)
    return linea

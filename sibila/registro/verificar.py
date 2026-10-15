"""Verificación de la cadena sellada sobre líneas EN MEMORIA (spec §8 punto 7:
el informe lista TODAS las roturas, no la primera — T-B6-4) + helpers puros
del ciclo de vida (D-T6-4).

El cruce fichero↔tabla y los anclajes git/ots son de la capa de datos: esta
capa no conoce ni fichero ni BD (`anclajes` se devuelve siempre vacío).
"""
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from .sellar import (CAMPOS, GENESIS, METRICAS, _RE_VENTANA, hash_linea,
                     parsear_ventana, validar_created_at)


@dataclass(frozen=True)
class ResultadoVerificacion:   # firma de Liskov §3, aceptada íntegra
    ok: bool
    n_lineas: int
    roturas: tuple
    anclajes: tuple


def vencida(created_at: str, ventana: str, dia: date) -> bool:
    """Candidatura a 'expirada' (D-T6-4): `dia > date(created_at) + ventana`,
    ESTRICTO: el día exacto del vencimiento NO está vencida (vector (d),
    T-B6-12). Aritmética de calendario determinista; quién la aplica es la
    capa de datos (la dedup por clave lógica solo mira pendientes NO vencidas
    usando esta misma regla — ratificación Orquestador, B1 de Liskov)."""
    validar_created_at(created_at)
    base = date.fromisoformat(created_at.split("T")[0])
    return dia > base + parsear_ventana(ventana)


def _dominio_ok(linea: dict) -> bool:
    """Chequeo de dominio/formato de UNA línea completa (8 claves exactas —
    T-B6-14): hash 64 hex, prev_hash 64 hex, metrica ∈ dominio, ventana casa
    D-T6-2, umbral número-string (D-T6-1), created_at D-T6-3, tema y criterio
    no vacíos, todo valor str."""
    if not isinstance(linea, dict) or set(linea) != set(CAMPOS) | {"hash"}:
        return False
    if not all(isinstance(linea[k], str) for k in list(CAMPOS) + ["hash"]):
        return False
    try:
        validar_created_at(linea["created_at"])
        parsear_ventana(linea["ventana"])
        Decimal(linea["umbral"])
    except (ValueError, InvalidOperation, TypeError, AttributeError):
        return False
    if not (re.match(r"^[0-9a-f]{64}$", linea.get("hash", "") or "") and
            re.match(r"^[0-9a-f]{64}$", linea.get("prev_hash", "") or "")):
        return False
    if linea["metrica"] not in METRICAS:
        return False
    if not linea["tema"] or not linea["criterio_acierto"]:
        return False
    return True


def verificar_lineas(lineas: tuple) -> ResultadoVerificacion:
    """Verifica la cadena completa. Chequeos EN ESTE ORDEN, anotando TODAS las
    roturas (nunca return temprano — T-B6-4): (1) génesis; por línea i (2)
    recomputación del hash, (3) encadenamiento prev_hash, (4) created_at no
    decreciente, (5) dominio. Lista vacía → registro vacío íntegro."""
    lineas = tuple(lineas)
    n = len(lineas)
    roturas = []
    if n and lineas[0].get("prev_hash") != GENESIS:
        roturas.append("génesis")
    # Encadenamiento contra el hash RECOMPUTADO de la línea anterior (no el
    # almacenado): así una edición de la línea i−1 se detecta en la línea i
    # aunque el editor recomputara solo su hash (spec §8, vector (e1)).
    rec_prev = None
    for i, ln in enumerate(lineas, 1):
        if not _dominio_ok(ln):
            roturas.append(f"dominio línea {i}")
            rec = ln.get("hash")   # sin dominio no hay recomputación fiable;
        else:                      # el informe sigue acumulando evidencia
            rec = hash_linea({k: ln[k] for k in CAMPOS})
            if ln["hash"] != rec:
                roturas.append(f"hash línea {i}")
        if i > 1:
            if ln.get("prev_hash") != rec_prev:
                roturas.append(f"prev_hash línea {i}")
            if ln.get("created_at", "") < lineas[i - 2].get("created_at", ""):
                roturas.append(f"orden línea {i}")
        rec_prev = rec
    return ResultadoVerificacion(ok=not roturas, n_lineas=n,
                                 roturas=tuple(roturas), anclajes=())

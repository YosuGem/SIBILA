"""Theil-Sen y Mann-Kendall hechos a mano (stdlib puro, spec §7, D-030).

Ventana (D-T5-5 + D-T5-7): el llamador comprueba que t−27…t está COMPLETA
(28 valores no-None de calendario) ANTES de llamar; si no, no se llama y la
salida es None en la fachada. Con ventana completa las posiciones de MK son
1…28 (insensible al espaciado); Theil-Sen recibe SIEMPRE las posiciones
ordinales de calendario (rev. cruzada N5, trampa T-B5-17).

Φ vía math.erf: única aproximación autorizada (stdlib, C, determinista;
prohibidas tablas o polinomios propios — trampa T-B5-6).
"""
import math
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .series import mediana

_C4 = Decimal("0.0001")


def _dec4(x: float) -> Decimal:
    return Decimal(str(x)).quantize(_C4, ROUND_HALF_UP)


@dataclass(frozen=True)
class ResultadoMK:
    s: int
    var_s: Decimal   # 4 dec. HALF_UP (corrección de empates SIEMPRE)
    z: Decimal       # 4 dec. (con corrección de continuidad)
    p: Decimal       # 4 dec., unilateral ↑, 1 − Φ(Z)


def theil_sen(posiciones: list, ys: list) -> Decimal:
    """Pendiente de Sen: mediana de (y_j − y_i)/(pos_j − pos_i) para i<j con
    y_j ≠ y_i (empatados en y no aportan). `posiciones` = ordinal de calendario
    (p.ej. date.toordinal()), OBLIGATORIO: con huecos los índices de lista
    mienten como denominadores (T-B5-17). 4 dec. HALF_UP al final.
    O(n²): n=28 → 378 pares, sobrado (T6 del plan).
    ValueError: len<2, longitudes distintas, posiciones no estrictamente
    crecientes, o todos los pares empatados (serie constante)."""
    if len(ys) < 2:
        raise ValueError("theil_sen exige ≥2 puntos")
    if len(posiciones) != len(ys):
        raise ValueError("posiciones y ys deben tener la misma longitud")
    if any(posiciones[i + 1] <= posiciones[i] for i in range(len(posiciones) - 1)):
        raise ValueError("posiciones no estrictamente crecientes")
    pend = [(ys[j] - ys[i]) / (posiciones[j] - posiciones[i])
            for i in range(len(ys)) for j in range(i + 1, len(ys))
            if ys[j] != ys[i]]
    if not pend:
        raise ValueError("serie constante: todas las pendientes empatadas")
    return _dec4(mediana(pend))


def mann_kendall(ys: list) -> ResultadoMK:
    """MK con corrección de empates SIEMPRE (una sola ruta de código) y
    corrección de continuidad (vector (d): sin empates daría Var=125,0; sin
    continuidad Z=3,1820 — T-B5-5).
    ValueError: len(ys)<4 (error de programación: la regla de negocio solo
    llama con ventana completa de 28, D-T5-7) o Var(S)=0 (serie constante:
    el llamador la trata como no-significativa, jamás como alerta)."""
    n = len(ys)
    if n < 4:
        raise ValueError("mann_kendall exige ≥4 puntos")
    S = sum((ys[j] > ys[i]) - (ys[j] < ys[i])
            for i in range(n) for j in range(i + 1, n))
    empates = sum(g * (g - 1) * (2 * g + 5) for g in Counter(ys).values())
    var = (n * (n - 1) * (2 * n + 5) - empates) / 18
    if var == 0:
        raise ValueError("Var(S)=0: serie constante, p no definida")
    if S > 0:
        z = (S - 1) / math.sqrt(var)
    elif S < 0:
        z = (S + 1) / math.sqrt(var)
    else:
        z = 0.0
    p = 1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return ResultadoMK(s=S, var_s=_dec4(var), z=_dec4(z), p=_dec4(p))

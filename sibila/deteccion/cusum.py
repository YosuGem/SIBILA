"""CUSUM unilateral superior con días ciegos (spec §7, plan_de_pruebas §3.3).

Reglas congeladas: S_0 = 0 ANTES del primer elemento; u=None (día ciego) →
SKIP: se anota el S vigente SIN cambiar (ni reset ni update — vector (c):
reset y skip dan el mismo cruce pero series distintas, trampa T-B5-4).
Este módulo es deliberadamente ciego al calendario: cada u_i ya llega
computada con la baseline rodante de SU PROPIO día (T-B5-1 la evita el
llamador; el vector (g) la caza).
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_C4 = Decimal("0.0001")


@dataclass(frozen=True)
class ResultadoCusum:
    """s = un S por día de la ventana de recursión (4 dec. HALF_UP, solo en la
    salida: la recursión interna sigue en float); cruce = índice 0-based del
    primer día con S_float > h (comparación en float interno, NO en el Decimal
    mostrado — trampa T-B5-3); None si no cruza."""
    s: tuple
    cruce: "int | None"


def cusum(us: list, k: float = 0.5, h: float = 4.0) -> ResultadoCusum:
    """S = max(0, S + u − k); u None → skip. ValueError si k<=0 u h<=0;
    lista vacía → ResultadoCusum((), None) (válido, no error)."""
    if k <= 0 or h <= 0:
        raise ValueError("k y h deben ser positivos")
    S = 0.0
    s = []
    cruce = None
    for i, u in enumerate(us):
        if u is not None:
            S = max(0.0, S + u - k)
        s.append(Decimal(str(S)).quantize(_C4, ROUND_HALF_UP))
        if cruce is None and S > h:
            cruce = i
    return ResultadoCusum(tuple(s), cruce)

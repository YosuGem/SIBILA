"""Calidad del documento (spec §6.5; fórmula FIJADA por Lovelace §4.5).

calidad = HALF_UP_4dec( (q_long + q_ent + q_idioma) / 3 )  ∈ [0,1]
- q_long = min(n, 200)/200, n = nº de palabras (D-L1)
- q_ent  = min(H_char/4,5, 1,0); H_char = entropía de Shannon (bits) sobre los
  caracteres del texto limpio INCLUYENDO espacios (rev. H2)
- q_idioma = confianza del detector si lang no None, si no 0,0

Siempre se escribe (marca de procesado, D-B4-05). Jamás lanza por contenido.
"""
import math
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

_C4 = Decimal("0.0001")


def _entropia_caracteres(texto: str) -> float:
    n = len(texto)
    if n == 0:
        return 0.0
    return -sum((c / n) * math.log2(c / n) for c in Counter(texto).values())


def score(texto_limpio: str, lang: "str | None", confianza: float = 0.0) -> float:
    """confianza = la del detector de idioma (q_idioma). Test mutante (rev. H7):
    llamar sin el parámetro debe cambiar el resultado cuando lang no es None."""
    if not isinstance(texto_limpio, str):
        raise ValueError("score espera str")
    n = len(texto_limpio.split())
    q_long = min(n, 200) / 200
    q_ent = min(_entropia_caracteres(texto_limpio) / 4.5, 1.0)
    q_idioma = float(confianza) if lang is not None else 0.0
    q = Decimal(str((q_long + q_ent + q_idioma) / 3)).quantize(_C4, ROUND_HALF_UP)
    return float(q)

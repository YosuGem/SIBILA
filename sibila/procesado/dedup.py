"""Dedup blando: SimHash propio (intra-fuente) y MinHash-LSH propio
(inter-fuente, Plan B stdlib pura — sin datasketch/numpy/scipy).

Algoritmos FIJADOS por vectores congelados (plan_de_pruebas §3.5 y plan
Lovelace §4.4); cambiarlos invalida los vectores.
"""
import hashlib
import re

from .stopwords import stopwords

# D-L1: palabra = secuencia maximal de [a-záéíóúüñ0-9'] (texto ya en minúsculas).
_RE_PALABRA = re.compile(r"[a-záéíóúüñ0-9']+")

P = 2 ** 61 - 1          # primo de Mersenne del esquema minhash
N = 128                  # nº de permutaciones
M32 = 0xFFFFFFFF
BANDAS = 32              # banding fijo b=32 × r=4 (umbral teórico ≈0,42)
FILAS = 4

Firma = tuple  # tuple[int, ...] de 128 (inmutable, serializable ",".join)

# Parámetros (a_i, b_i) derivados de SHA-256: reproducibles sin RNG.
_A = tuple(
    int.from_bytes(hashlib.sha256(b"sibila-minhash-a" + i.to_bytes(2, "big")).digest()[:8], "big") % (P - 1) + 1
    for i in range(N)
)
_B = tuple(
    int.from_bytes(hashlib.sha256(b"sibila-minhash-b" + i.to_bytes(2, "big")).digest()[:8], "big") % (P - 1) + 1
    for i in range(N)
)


def _palabras(texto_limpio: str) -> list:
    return _RE_PALABRA.findall(texto_limpio)


def _content_words(texto_limpio: str, lang=None) -> list:
    sw = stopwords(lang)
    return [w for w in _palabras(texto_limpio)
            if len(w) >= 3 and w not in sw]


def simhash(texto_limpio: str) -> str | None:
    """hex(16) minúsculas; None si <50 content words (spec §6.4).

    Shingles de 3 content words consecutivas (" ".join) → SHA-256 → 64 bits BE
    → ±1 por bit con barrido CRUZADO: el bit i del hash (LSB=0) vota por la
    posición 63−i del resultado (rev. H1; la lectura posición-preservante es
    INCORRECTA y el test la mata).
    """
    cw = _content_words(texto_limpio, None)
    if len(cw) < 50:
        return None
    return _simhash_de_palabras(cw)


def _simhash_de_palabras(palabras) -> str:
    v = [0] * 64
    for k in range(len(palabras) - 2):
        h = int.from_bytes(
            hashlib.sha256(" ".join(palabras[k:k + 3]).encode("utf-8")).digest()[:8],
            "big",
        )
        for i in range(64):
            v[63 - i] += 1 if (h >> i) & 1 else -1
    r = 0
    for p in range(64):
        if v[p] > 0:
            r |= 1 << p
    return format(r, "016x")


def hamming(h1: str, h2: str) -> int:
    """Distancia de Hamming 0..64; XOR enmascarado a 64 bits.
    ValueError si no son hex(16)."""
    for h in (h1, h2):
        if not isinstance(h, str) or len(h) != 16:
            raise ValueError("hamming espera hex(16)")
        try:
            int(h, 16)
        except ValueError:
            raise ValueError("hamming espera hex(16)") from None
    return bin((int(h1, 16) ^ int(h2, 16)) & 0xFFFFFFFFFFFFFFFF).count("1")


def shingles(texto_limpio: str) -> frozenset:
    """5-gramas de TODAS las palabras (no solo content words) sobre texto
    limpio; frozenset() vacío si <5 palabras."""
    w = _palabras(texto_limpio)
    if len(w) < 5:
        return frozenset()
    return frozenset(" ".join(w[k:k + 5]) for k in range(len(w) - 4))


def firma_minhash(shs: frozenset) -> Firma:
    """Firma de 128 enteros. shs vacío → centinela 128×M32 (J consigo misma=1;
    la capa de datos NO inserta firmas de docs con <5 palabras)."""
    if not shs:
        return (M32,) * N
    hs = [int.from_bytes(hashlib.sha256(s.encode("utf-8")).digest()[:4], "big")
          for s in shs]
    f = []
    for i in range(N):
        a, b = _A[i], _B[i]
        f.append(min(((a * h + b) % P) & M32 for h in hs))
    return tuple(f)


def _jaccard_est(f1: Firma, f2: Firma) -> float:
    return sum(1 for i in range(N) if f1[i] == f2[i]) / N


class IndiceMinHash:
    """Índice LSH en memoria, banding fijo b=32 bandas × r=4 filas.

    El parámetro `umbral` fija el umbral de CONFIRMACIÓN por Jaccard estimada
    (conteo de posiciones iguales / 128), NO el banding (fijo; matiz de
    interfaz §6 aceptado). Determinista por construcción.
    """

    def __init__(self, umbral: float = 0.5):
        self.umbral = float(umbral)
        self._firmas = {}                       # clave -> firma
        self._bandas = [dict() for _ in range(BANDAS)]  # hash_banda -> set[clave]

    @staticmethod
    def _clave_banda(firma: Firma, b: int) -> tuple:
        # La propia sub-tupla es la clave: determinista sin depender de hash().
        return firma[b * FILAS:(b + 1) * FILAS]

    def insertar(self, clave: int, firma: Firma) -> None:
        self._firmas[clave] = firma
        for b in range(BANDAS):
            self._bandas[b].setdefault(self._clave_banda(firma, b), set()).add(clave)

    def consultar(self, firma: Firma) -> list:
        """Ids candidatos que comparten ≥1 banda y pasan J_est ≥ umbral,
        ordenados ASC (contrato)."""
        cand = set()
        for b in range(BANDAS):
            cand |= self._bandas[b].get(self._clave_banda(firma, b), set())
        return sorted(c for c in cand
                      if _jaccard_est(self._firmas[c], firma) >= self.umbral)

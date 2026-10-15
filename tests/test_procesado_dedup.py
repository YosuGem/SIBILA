"""Tests puros de procesado/dedup.py: vector (e) §3.5, MinHash Plan B (§4.4)
e IndiceMinHash (banding fijo b=32/r=4, umbral = confirmación J_est)."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import hashlib
import unittest

from sibila.procesado import dedup
from sibila.procesado.dedup import (M32, N, IndiceMinHash, firma_minhash,
                                    hamming, shingles, simhash)

TEXTO_A = ("quantum computing breakthrough researchers announce qubit "
           "stability milestone laboratory experiment physics")
TEXTO_B = ("terremoto costa ciudad evacuación pánico olas gigantes alerta "
           "temprana sirenas vecinos huyen monte")

# sh1 congelado (plan Lovelace §5.2): 5-gramas de
# "el banco central sube tipos interes inflacion hoy"
SH1 = frozenset([
    "el banco central sube tipos",
    "banco central sube tipos interes",
    "central sube tipos interes inflacion",
    "sube tipos interes inflacion hoy",
])

# Textos de discriminación (base / casi-copia / ajeno)
BASE = ("el banco central europeo sube los tipos de interes mientras la "
        "inflacion sigue por encima del objetivo y los mercados esperan "
        "nuevas decisiones del consejo de gobierno esta semana")
V1 = ("el banco central europeo sube los tipos de interes mientras la "
      "inflacion sigue por encima del objetivo y los mercados esperan "
      "nuevas decisiones del consejo de gobierno esta misma semana ahora")
AJENO = ("la receta de la tortilla de patatas lleva huevos aceite sal y "
         "cebolla pochada a fuego lento hasta cuajar todo bien despacio "
         "en una sarten honda y amplia de cocina tradicional casera")


def _simhash_posicion_preservante(palabras):
    """Lectura INCORRECTA (bit i → posición i): el test exige que difiera."""
    v = [0] * 64
    for k in range(len(palabras) - 2):
        h = int.from_bytes(hashlib.sha256(
            " ".join(palabras[k:k + 3]).encode("utf-8")).digest()[:8], "big")
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    return format(sum(1 << p for p in range(64) if v[p] > 0), "016x")


class TestSimhashVectorE(unittest.TestCase):
    """Vector (e) oficial §3.5 recomputado (D-030: nunca confiar sin recomputar)."""

    def test_vectores_congelados(self):
        self.assertEqual(dedup._simhash_de_palabras(TEXTO_A.split()),
                         "a554f1f06d019f4e")  # ≥2⁶³: el caso que rompió Fase 0
        self.assertEqual(dedup._simhash_de_palabras(TEXTO_B.split()),
                         "2659e5d1f3c8304c")

    def test_lectura_preservante_es_la_incorrecta(self):
        # Muerde: si alguien "corrige" el barrido cruzado, este test muere.
        self.assertEqual(_simhash_posicion_preservante(TEXTO_A.split()),
                         "72f980b60f8f2aa5")
        self.assertNotEqual(dedup._simhash_de_palabras(TEXTO_A.split()),
                            "72f980b60f8f2aa5")

    def test_hamming_vectores(self):
        self.assertEqual(hamming("a554f1f06d019f4e", "2659e5d1f3c8304c"), 26)
        self.assertEqual(hamming("a554f1f06d019f4e", "a554f1f06d019f4e"), 0)
        self.assertEqual(hamming("0000000000000000", "ffffffffffffffff"), 64)

    def test_hamming_valueerror(self):
        for malo in ("a554f1f06d019f4", "a554f1f06d019f4eX", 123, None):
            with self.assertRaises(ValueError):
                hamming(malo, "a554f1f06d019f4e")

    def test_umbral_50_content_words(self):
        self.assertIsNone(simhash(TEXTO_A))          # 11 content words
        self.assertIsNone(simhash(" ".join(["palabra"] * 49)))
        h = simhash(" ".join(["palabra"] * 50))
        self.assertIsNotNone(h)
        self.assertEqual(len(h), 16)


class TestMinHashVector(unittest.TestCase):
    def test_firma_congelada(self):
        f = firma_minhash(SH1)
        self.assertEqual(len(f), N)
        self.assertEqual(f[:8], (174516129, 1946998837, 18401200, 507896715,
                                 328497385, 480120972, 827062860, 690877597))
        self.assertEqual(f[-4:], (83773961, 1102805117, 162093267, 598559020))

    def test_serializacion_congelada(self):
        f = firma_minhash(SH1)
        self.assertEqual(
            hashlib.sha256(",".join(map(str, f)).encode("utf-8")).hexdigest(),
            "319d9d08703e196f66c479b428926e8f2c67b7892e3015f17e3fa4c93b85c366")

    def test_determinista_entre_llamadas(self):
        self.assertEqual(firma_minhash(SH1), firma_minhash(SH1))

    def test_shingles(self):
        self.assertEqual(shingles("el banco central sube tipos interes "
                                  "inflacion hoy"), SH1)
        self.assertEqual(shingles("solo cuatro palabras aqui"), frozenset())

    def test_centinela_vacio(self):
        f = firma_minhash(frozenset())
        self.assertEqual(f, (M32,) * N)
        # J consigo misma = 1 (la capa de datos NO inserta estos docs)
        self.assertEqual(dedup._jaccard_est(f, f), 1.0)


class TestIndiceMinHash(unittest.TestCase):
    def test_discriminacion(self):
        fb = firma_minhash(shingles(BASE))
        f1 = firma_minhash(shingles(V1))
        fa = firma_minhash(shingles(AJENO))
        ind = IndiceMinHash()  # umbral de confirmación J_est = 0,5
        ind.insertar(1, fb)
        # Casi-copia: comparte banda y supera la confirmación
        self.assertEqual(ind.consultar(f1), [1])
        self.assertGreaterEqual(dedup._jaccard_est(fb, f1), 0.5)
        # Texto ajeno: ni bandas compartidas ni J_est
        self.assertEqual(ind.consultar(fa), [])
        self.assertEqual(dedup._jaccard_est(fb, fa), 0.0)

    def test_umbral_confirmacion_filtra(self):
        fb = firma_minhash(shingles(BASE))
        f1 = firma_minhash(shingles(V1))
        ind = IndiceMinHash(umbral=0.99)   # confirmación estricta
        ind.insertar(1, fb)
        self.assertEqual(ind.consultar(f1), [])      # comparte banda pero no J
        self.assertEqual(ind.consultar(fb), [1])     # idéntica sí pasa

    def test_consultar_orden_asc(self):
        f = firma_minhash(shingles(BASE))
        ind = IndiceMinHash()
        for clave in (9, 3, 7):
            ind.insertar(clave, f)
        self.assertEqual(ind.consultar(f), [3, 7, 9])


if __name__ == "__main__":
    unittest.main()

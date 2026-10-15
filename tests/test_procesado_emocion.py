"""Tests puros de procesado/emocion.py con MINI-LEXICÓN fixture propio en
tests/fixtures/procesado/ (formato congelado: ver docstring de emocion.py).
NUNCA el NRC real en tests unitarios. VADER puede faltar: se mockea."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import tempfile
import unittest
from pathlib import Path

from sibila import SibilaError
from sibila.procesado.emocion import (EmoDoc, Lexicos, agregar_dia,
                                      cargar_lexicos, vector)

FIX = Path(__file__).parent / "fixtures" / "procesado"
CFG = {"nrc_vad_en": FIX / "vad_en.txt", "nrc_vad_es": FIX / "vad_es.txt",
       "nrc_emociones_en": FIX / "emo_en.txt", "nrc_emociones_es": FIX / "emo_es.txt"}

# Texto ES: content words tras stopwords = [alegria, confianza, llenan, fiesta,
# sorpresa]; casadas = alegria(0.9,0.6) confianza(0.8,0.2) sorpresa(0.5,0.7) ya
# reescaladas (v'=2v−1). V=(0.9+0.8+0.5)/3=0.7333, A=(0.6+0.2+0.7)/3=0.5.
TEXTO_ES = "la alegria y la confianza llenan la fiesta de sorpresa"


class MockVader:
    def polarity_scores(self, texto):
        return {"compound": 0.5}


def _lex(**kw):
    base = cargar_lexicos(CFG, verificar_sha=False)
    if not kw:
        return base
    datos = dict(vad_en=base.vad_en, vad_es=base.vad_es, emo_en=base.emo_en,
                 emo_es=base.emo_es, vader=base.vader)
    datos.update(kw)
    return Lexicos(**datos)


class TestCargarLexicos(unittest.TestCase):
    def test_fixture_carga(self):
        lex = _lex()
        self.assertIsNotNone(lex)
        # Reescalado ES v1 [0,1] → [−1,1] tanto en V como en A (floats crudos)
        v, a = lex.vad_es["alegria"]
        self.assertAlmostEqual(v, 0.9)
        self.assertAlmostEqual(a, 0.6)
        self.assertEqual(lex.vad_en["joy"], (0.9, 0.6))  # EN v2 ya en [−1,1]

    def test_ausente_degrada_a_none(self):
        self.assertIsNone(cargar_lexicos({}))
        cfg = dict(CFG)
        cfg["nrc_vad_es"] = Path("/no/existe.txt")
        self.assertIsNone(cargar_lexicos(cfg, verificar_sha=False))

    def test_corrupto_es_fallo_visible(self):
        with tempfile.TemporaryDirectory(prefix="sibila José Pérez ") as td:
            ruta = Path(td) / "vad_malo.txt"
            ruta.write_text("Term\tV\tA\nok\t0.5\t0.5\nmala\tNO_NUM\t0.5\n",
                            encoding="utf-8")
            cfg = dict(CFG)
            cfg["nrc_vad_en"] = ruta
            with self.assertRaises(SibilaError):
                cargar_lexicos(cfg, verificar_sha=False)


class TestVector(unittest.TestCase):
    def test_vector_es_congelado(self):
        e = vector(_lex(), TEXTO_ES, "es")
        self.assertEqual(e.v, 0.7333)
        self.assertEqual(e.a, 0.5)
        self.assertEqual(e.emociones, (0, 0, 0, 0, 1, 0, 1, 1))
        self.assertEqual(e.n_casadas, 3)
        self.assertEqual(e.cobertura, 0.6)

    def test_vector_en_con_vader(self):
        # EN: V = (V_NRC + compound_VADER)/2; A solo de NRC
        texto = "the joy and trust fill the party with surprise today"
        e = vector(_lex(vader=MockVader()), texto, "en")
        # content words: joy, trust, fill, party, surprise, today (6)
        # casadas: joy(0.9), trust(0.8), surprise(0.5) → V_NRC=0.7333
        # V=(0.7333…+0.5)/2=0.6167; A=(0.6+0.2+0.7)/3=0.5
        self.assertEqual(e.v, 0.6167)
        self.assertEqual(e.a, 0.5)
        self.assertEqual(e.cobertura, 0.5)

    def test_none_si_lex_ausente_o_idioma_no_soportado(self):
        self.assertIsNone(vector(None, TEXTO_ES, "es"))
        self.assertIsNone(vector(_lex(), TEXTO_ES, "fr"))
        self.assertIsNone(vector(_lex(), TEXTO_ES, None))

    def test_none_menos_de_3_casadas(self):
        self.assertIsNone(vector(_lex(), "la alegria y la confianza", "es"))

    def test_none_cobertura_baja(self):
        # 3 casadas entre 12 content words → 0,25 < 0,30
        texto = ("alegria confianza sorpresa perro gato mesa silla libro "
                 "calle puerta ventana coche")
        self.assertIsNone(vector(_lex(), texto, "es"))

    def test_en_sin_vader_devuelve_none(self):  # rev. Hamilton M1 / Dijkstra M3
        # Léxicos presentes pero VADER no importable: jamás V=(V_NRC+0)/2
        # (sesgo silencioso a la mitad); vector() = None para EN.
        texto = "the joy and trust fill the party with surprise today"
        self.assertIsNone(vector(_lex(vader=None), texto, "en"))

    def test_es_sin_vader_no_cambia(self):
        # ES no usa VADER: vector normal aunque vader=None.
        e = vector(_lex(vader=None), TEXTO_ES, "es")
        self.assertEqual(e.v, 0.7333)
        self.assertEqual(e.a, 0.5)

    def test_aviso_una_vez_por_carga_si_vader_ausente(self):
        from unittest import mock
        from sibila.procesado import emocion
        with mock.patch.object(emocion, "_cargar_vader", return_value=None):
            with self.assertLogs("sibila.procesado.emocion", level="WARNING") as cm:
                emocion.cargar_lexicos(CFG, verificar_sha=False)
        avisos = [m for m in cm.output if "VADER" in m]
        self.assertEqual(len(avisos), 1)         # UNA vez por carga


class TestAgregarDia(unittest.TestCase):
    E1 = EmoDoc(v=0.5, a=0.2, emociones=(0,) * 8, n_casadas=3, cobertura=0.5)
    E2 = EmoDoc(v=-0.5, a=0.8, emociones=(0,) * 8, n_casadas=4, cobertura=0.6)
    E3 = EmoDoc(v=0.1, a=-0.4, emociones=(0,) * 8, n_casadas=3, cobertura=0.4)

    def test_vector_numerico_fijo(self):
        # w = 1,2,3 → n_efectivo = 36/14 = 2,5714
        r = agregar_dia([(self.E1, 1.0), (self.E2, 2.0), (self.E3, 3.0)])
        v, a, n, nef = r
        self.assertEqual(n, 3)
        self.assertEqual(nef, 2.5714)
        # V = (0.5·1 − 0.5·2 + 0.1·3)/6 = −0.2/6 = −0,0333
        self.assertEqual(v, -0.0333)
        # A = (0.2·1 + 0.8·2 − 0.4·3)/6 = 0.6/6 = 0,1
        self.assertEqual(a, 0.1)

    def test_none_vacio_y_sigma_w2_cero(self):
        self.assertIsNone(agregar_dia([]))
        self.assertIsNone(agregar_dia([(self.E1, 0.0), (self.E2, 0.0)]))


if __name__ == "__main__":
    unittest.main()

"""Tests puros de procesado/idioma.py. El contrato es el UMBRAL, no fastText:
se usa mock del Detector salvo que el modelo real esté disponible.
lingua es efímera entre sesiones: skipUnless si no es importable."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
_lingua = _P("/tmp/lingua_deps")  # efímera, solo esta sesión
if _lingua.is_dir() and str(_lingua) not in _sys.path:
    _sys.path.append(str(_lingua))
import tempfile
import unittest
from pathlib import Path

from sibila import SibilaError
from sibila.procesado.idioma import cargar_detector, detectar

import importlib.util as _ilu

# find_spec (no import literal): el guardián AST congelado de empaquetado
# (test_empaquetado) prohíbe imports no-stdlib en tests/.
HAY_LINGUA = _ilu.find_spec("lingua") is not None
HAY_FASTTEXT = _ilu.find_spec("fasttext") is not None

TEXTO_ES = ("el banco central europeo mantiene los tipos de interes mientras "
            "la inflacion sigue por encima del objetivo oficial")


class MockDetector:
    """Sustituto del FastText de fasttext-predict (misma interfaz predict)."""

    def __init__(self, etiqueta, confianza):
        self._e, self._c = etiqueta, confianza

    def predict(self, texto, k=1):
        return [self._e], [self._c]


class TestCargarDetector(unittest.TestCase):
    def test_ausente_degrada_a_none(self):
        self.assertIsNone(cargar_detector(None))
        self.assertIsNone(cargar_detector("/no/existe/lid.176.ftz"))

    @unittest.skipUnless(HAY_FASTTEXT, "fasttext-predict no instalable aquí")
    def test_corrupto_es_fallo_visible(self):
        # Ruta con acentos y espacios (trampa T-11): fichero presente pero
        # ilegible como modelo → SibilaError, no degradación silenciosa.
        with tempfile.TemporaryDirectory(prefix="sibila José Pérez ") as td:
            ruta = Path(td) / "lid.176.ftz"
            ruta.write_bytes(b"esto no es un modelo fasttext")
            with self.assertRaises(SibilaError):
                cargar_detector(ruta)


class TestDetectar(unittest.TestCase):
    def test_detector_none(self):
        self.assertEqual(detectar(None, TEXTO_ES), (None, 0.0))

    def test_menos_de_3_palabras(self):
        det = MockDetector("__label__es", 0.99)
        self.assertEqual(detectar(det, "hola mundo"), (None, 0.0))
        self.assertEqual(detectar(det, "hola"), (None, 0.0))
        self.assertEqual(detectar(det, ""), (None, 0.0))

    def test_confianza_alta_directo(self):
        det = MockDetector("__label__es", 0.95)
        self.assertEqual(detectar(det, TEXTO_ES), ("es", 0.95))

    def test_confianza_cero(self):
        det = MockDetector("__label__es", 0.0)
        self.assertEqual(detectar(det, TEXTO_ES), (None, 0.0))

    @unittest.skipUnless(HAY_LINGUA, "lingua no disponible (efímera)")
    def test_dudoso_cae_en_lingua(self):
        # fastText dudoso (0,5) → lingua decide con su propio umbral 0,80
        det = MockDetector("__label__pt", 0.5)
        lang, conf = detectar(det, TEXTO_ES)
        self.assertEqual(lang, "es")
        self.assertGreaterEqual(conf, 0.80)

    def test_dudoso_sin_lingua_degrada_a_none(self):
        # Con lingua ausente el camino dudoso degrada a (None, 0.0);
        # este test solo tiene sentido cuando lingua NO es importable.
        if HAY_LINGUA:
            self.skipTest("lingua presente: el camino de degradación no aplica")
        det = MockDetector("__label__pt", 0.5)
        self.assertEqual(detectar(det, TEXTO_ES), (None, 0.0))

    def test_detector_lingua_se_construye_una_vez(self):  # rev. Hamilton M4
        # El builder (8 modelos; GL no existe en lingua 2.2.0, D-066) se construye UNA vez por proceso, no por
        # llamada: dos detectar() dudosos → un solo build(). Mutación (quitar
        # la caché) → 2 builds → muere.
        import sys
        import types
        from unittest import mock
        from sibila.procesado import idioma
        llamadas = {"build": 0}

        class BuilderFalso:
            @classmethod
            def from_iso_codes_639_1(cls, *codigos):
                assert len(codigos) == 8
                return cls()

            def build(self):
                llamadas["build"] += 1
                return self

            def compute_language_confidence_values(self, texto):
                return [types.SimpleNamespace(
                    value=0.9,
                    language=types.SimpleNamespace(
                        iso_code_639_1=types.SimpleNamespace(name="ES")))]

        codigos = types.SimpleNamespace(**{c: i for i, c in enumerate(
            ("ES", "EN", "PT", "FR", "DE", "IT", "CA", "EU"))})
        lingua_falso = types.SimpleNamespace(
            LanguageDetectorBuilder=BuilderFalso, IsoCode639_1=codigos)
        det = MockDetector("__label__pt", 0.5)   # dudoso → cae en lingua
        with mock.patch.dict(sys.modules, {"lingua": lingua_falso}):
            idioma._LINGUA_CACHE = None
            try:
                self.assertEqual(detectar(det, TEXTO_ES), ("es", 0.9))
                self.assertEqual(detectar(det, TEXTO_ES), ("es", 0.9))
            finally:
                idioma._LINGUA_CACHE = None      # no contaminar otros tests
        self.assertEqual(llamadas["build"], 1)


if __name__ == "__main__":
    unittest.main()

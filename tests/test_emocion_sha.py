"""T-SHA-1..4 (T2 §1): SHA256_ESPERADOS real cierra R1-Hamilton de B4
(no-op silencioso de verificación). Los hashes se computaron sobre los
artefactos NORMALIZADOS (tools/descargar_recursos.py) descargados de las
fuentes oficiales NRC y verificados por doble descarga (D-030).
T-SHA-3 es skipUnless si los léxicos reales no están en <data_dir>/recursos
(mismo patrón que el skip de lingua)."""
import re
import unittest
from pathlib import Path

from sibila.procesado import emocion
from sibila import SibilaError

CLAVES = {"nrc_vad_en.txt", "nrc_vad_es.txt",
          "nrc_emociones_en.txt", "nrc_emociones_es.txt"}


class TestShaEsperados(unittest.TestCase):
    def test_t_sha_1_dict_no_vacio_y_claves_exactas(self):
        # R1-Hamilton: vacío o clave renombrada = verificación desactivada
        self.assertTrue(emocion.SHA256_ESPERADOS, "dict vacío: no-op (R1)")
        self.assertEqual(set(emocion.SHA256_ESPERADOS), CLAVES)

    def test_t_sha_2_valores_hex_64_minusculas(self):
        for nombre, h in emocion.SHA256_ESPERADOS.items():
            self.assertRegex(h, r"\A[0-9a-f]{64}\Z", nombre)

    def test_t_sha_4_nombre_ausente_no_verifica(self):
        # Comportamiento congelado: un nombre FUERA del dict no se verifica;
        # quien "lo arregle" debe registrarlo (este test lo hace visible).
        self.assertIsNone(emocion.SHA256_ESPERADOS.get("otro_lexico.txt"))


class TestShaConLexicosReales(unittest.TestCase):
    RECURSOS = Path(__file__).resolve().parent.parent / "datos" / "recursos"

    def setUp(self):
        if not all((self.RECURSOS / n).is_file() for n in CLAVES):
            self.skipTest("léxicos NRC reales no descargados "
                          "(corre tools/descargar_recursos.py; mismo patrón "
                          "que el skip de lingua)")
        self.rutas = {n[:-4]: self.RECURSOS / n for n in CLAVES}

    def test_t_sha_3_lexicos_reales_verifican(self):
        lex = emocion.cargar_lexicos(self.rutas, verificar_sha=True)
        self.assertIsNotNone(lex)
        self.assertGreater(len(lex.vad_en), 40000)

    def test_t_sha_3b_hash_alterado_es_sibilaerror(self):
        mal = self.RECURSOS / "nrc_vad_en_mal.txt"
        mal.write_bytes(b"palabra\t0.1\t0.2\n")   # no está en el dict…
        try:
            # …pero el nombre SÍ registrado con contenido alterado sí falla:
            rutas = dict(self.rutas)
            corrupto = self.RECURSOS / "nrc_vad_en.txt"
            # no tocamos el real: copiamos con el MISMO nombre en otra carpeta
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                td = Path(td)
                for n in CLAVES:
                    (td / n).write_bytes((self.RECURSOS / n).read_bytes())
                (td / "nrc_vad_en.txt").write_bytes(b"palabra\t0.1\t0.2\n")
                with self.assertRaises(SibilaError):
                    emocion.cargar_lexicos({n[:-4]: td / n for n in CLAVES},
                                           verificar_sha=True)
        finally:
            mal.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

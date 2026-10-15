"""Guardián de skips (rev. Hamilton M1 · T2-R1): los skips condicionales de la
batería están DOCUMENTADOS y son exactamente 3 en un entorno sin recursos:
  - test_emocion_sha.py: 2 T-SHA-3 (TestShaConLexicosReales: léxicos NRC
    reales ausentes → skipTest en setUp, condición anclada a datos/recursos)
  - test_procesado_idioma.py: 1 (lingua efímera → skipUnless HAY_LINGUA)
Sin guardián, un skip podría quedar permanente e invisible si los recursos
desaparecen del repo, o alguien podría quitar la condición sin ruido.
Además se ancla el inventario de decoradores @skipUnless (3: git, fasttext,
lingua): cualquiera nuevo o quitado mata este guardián (texto anclado).
"""
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent


class TestGuardianSkips(unittest.TestCase):
    def test_exactamente_3_decoradores_skipunless(self):  # rev. Hamilton M1
        # git (anclaje), fasttext y lingua (idioma): el inventario es cerrado.
        # (este propio fichero se excluye: contiene el patrón como literal)
        marca = "@unittest." + "skipUnless("
        total = sum(p.read_text(encoding="utf-8").count(marca)
                    for p in TESTS.glob("test_*.py"))
        self.assertEqual(total, 3,
                         "skipUnless != 3: documenta el cambio en este guardián")

    def test_t_sha_3_llevan_su_condicion(self):
        # Los 2 T-SHA-3 no usan decorador: skipTest en setUp anclado a la
        # presencia REAL de los 4 léxicos NRC — si se quita la condición o el
        # texto, este guardián muere (el skip nunca es silencioso).
        sha = (TESTS / "test_emocion_sha.py").read_text(encoding="utf-8")
        self.assertIn('self.skipTest("léxicos NRC reales no descargados', sha)
        # …y la CONDICIÓN del skip, no solo el literal (rev. Dijkstra M5):
        # `if not all(...)` → `if True:` muere aquí
        self.assertIn("if not all((self.RECURSOS / n).is_file() for n in CLAVES):",
                      sha)
        self.assertIn("class TestShaConLexicosReales(unittest.TestCase):", sha)
        self.assertEqual(sha.count("def test_t_sha_3"), 2,
                         "los T-SHA-3 con skip condicionado son exactamente 2")

    def test_lingua_lleva_skipunless(self):
        idi = (TESTS / "test_procesado_idioma.py").read_text(encoding="utf-8")
        self.assertIn("@unittest." + "skipUnless(HAY_LINGUA", idi)


if __name__ == "__main__":
    unittest.main()

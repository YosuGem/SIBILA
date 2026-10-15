"""Guardián AST (espejo Bloque 2, test §5.9): sibila/procesado/* NO importa
sqlite3 / sibila.db / requests / datasketch / numpy / scipy, y los imports de
fasttext/lingua/vaderSentiment son PEREZOSOS (nivel de función, nunca de
módulo) para que el paquete se importe sin las dependencias pesadas."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import ast
import importlib
import unittest
from pathlib import Path

PAQ = Path(__file__).resolve().parent.parent / "sibila" / "procesado"

PROHIBIDOS = {"sqlite3", "requests", "datasketch", "numpy", "scipy", "sibila.db"}
PEREZOSOS = {"fasttext", "fasttext_predict", "lingua", "vaderSentiment"}


def _imports(nodo, nivel_modulo=True):
    """(modulo_raiz, es_top_level) de todos los imports del árbol."""
    for sub in ast.walk(nodo):
        if isinstance(sub, (ast.Import, ast.ImportFrom)):
            if isinstance(sub, ast.Import):
                for a in sub.names:
                    yield a.name.split(".")[0], sub.col_offset == 0
            else:
                if sub.level == 0 and sub.module:
                    yield sub.module.split(".")[0], sub.col_offset == 0


class TestGuardianAst(unittest.TestCase):
    def test_sin_imports_prohibidos(self):
        for py in sorted(PAQ.glob("*.py")):
            arbol = ast.parse(py.read_text(encoding="utf-8"))
            for mod, _ in _imports(arbol):
                self.assertNotIn(mod, PROHIBIDOS, f"{py.name} importa {mod}")
            # sibila.db vía "from sibila import db" también prohibida
            for sub in ast.walk(arbol):
                if isinstance(sub, ast.ImportFrom) and sub.module == "sibila":
                    for a in sub.names:
                        self.assertNotEqual(a.name, "db",
                                            f"{py.name} importa sibila.db")

    def test_dependencias_pesadas_perezosas(self):
        for py in sorted(PAQ.glob("*.py")):
            arbol = ast.parse(py.read_text(encoding="utf-8"))
            for mod, top in _imports(arbol):
                if mod in PEREZOSOS:
                    self.assertFalse(top, f"{py.name} importa {mod} a nivel de módulo")

    def test_paquete_importable_sin_deps_pesadas(self):
        # El paquete entero se importa aunque falten lingua/fasttext/vader.
        for m in ("limpieza", "idioma", "dedup", "calidad", "bot_heur",
                  "emocion", "ngramas", "stopwords"):
            importlib.import_module(f"sibila.procesado.{m}")


if __name__ == "__main__":
    unittest.main()

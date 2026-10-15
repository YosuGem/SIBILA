"""Guardianes de alertas/ e informe/: pureza AST (sin sqlite3/red/disco/
subprocess) y anti-reloj (T-B7-6: prohibido now/today/utcnow; `ahora` entra
siempre como parámetro)."""
import ast
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "sibila"
MODULOS = [RAIZ / "alertas" / "reglas.py", RAIZ / "alertas" / "cooldown.py",
           RAIZ / "informe" / "render.py",
           RAIZ / "alertas" / "__init__.py", RAIZ / "informe" / "__init__.py"]

PROHIBIDOS = {"sqlite3", "subprocess", "socket", "requests", "os", "pathlib",
              "random"}
RELOJ = {"now", "today", "utcnow"}


class TestGuardianPuroB7(unittest.TestCase):
    def test_stdlib_puro(self):
        permitidos = set(sys.stdlib_module_names) | {"sibila"}
        for py in MODULOS:
            for nodo in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
                if isinstance(nodo, ast.Import):
                    for a in nodo.names:
                        self.assertIn(a.name.split(".")[0], permitidos)
                        self.assertNotIn(a.name.split(".")[0], PROHIBIDOS)
                elif isinstance(nodo, ast.ImportFrom):
                    if nodo.level == 0 and nodo.module:
                        self.assertIn(nodo.module.split(".")[0], permitidos)
                        self.assertNotIn(nodo.module.split(".")[0], PROHIBIDOS)

    def test_sin_reloj_ni_disco(self):
        for py in MODULOS:
            for nodo in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
                if isinstance(nodo, ast.Attribute):
                    self.assertNotIn(nodo.attr, RELOJ,
                                     f"{py.name} usa reloj: .{nodo.attr}")
                if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
                    self.assertNotEqual(nodo.func.id, "open")

    def test_paquetes_importables(self):
        __import__("sibila.alertas.reglas")
        __import__("sibila.alertas.cooldown")
        __import__("sibila.informe.render")


if __name__ == "__main__":
    unittest.main()

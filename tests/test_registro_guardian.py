"""Guardianes de registro/: pureza de imports (espejo T-B5/T-B6), anti-reloj
(T-B6-13: prohibido now/today/utcnow en TODO el paquete), anti-disco y
anti-subprocess. Determinismo PYTHONHASHSEED se demuestra en ejecución."""
import ast
import sys
import unittest
from pathlib import Path

PAQ = Path(__file__).resolve().parent.parent / "sibila" / "registro"

PROHIBIDOS_IMPORT = {"sqlite3", "subprocess", "socket", "requests", "os",
                     "pathlib", "random"}
PROHIBIDOS_ATTR = {"now", "today", "utcnow"}     # reloj (T-B6-13)
PROHIBIDOS_NOMBRE = {"open"}                     # disco


class TestGuardianRegistro(unittest.TestCase):
    def test_stdlib_puro(self):
        permitidos = set(sys.stdlib_module_names) | {"sibila"}
        for py in sorted(PAQ.glob("*.py")):
            for nodo in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
                if isinstance(nodo, ast.Import):
                    for a in nodo.names:
                        self.assertIn(a.name.split(".")[0], permitidos,
                                      f"{py.name} importa {a.name}")
                        self.assertNotIn(a.name.split(".")[0], PROHIBIDOS_IMPORT)
                elif isinstance(nodo, ast.ImportFrom):
                    if nodo.level == 0 and nodo.module:
                        self.assertIn(nodo.module.split(".")[0], permitidos,
                                      f"{py.name} importa {nodo.module}")
                        self.assertNotIn(nodo.module.split(".")[0],
                                         PROHIBIDOS_IMPORT)

    def test_sin_reloj_ni_disco(self):
        for py in sorted(PAQ.glob("*.py")):
            arbol = ast.parse(py.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Attribute):
                    self.assertNotIn(nodo.attr, PROHIBIDOS_ATTR,
                                     f"{py.name} usa reloj: .{nodo.attr}")
                if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
                    self.assertNotIn(nodo.func.id, PROHIBIDOS_NOMBRE,
                                     f"{py.name} abre disco: {nodo.func.id}(")

    def test_paquete_importable(self):
        for m in ("canonico", "derivar", "sellar", "verificar"):
            __import__(f"sibila.registro.{m}")


if __name__ == "__main__":
    unittest.main()

"""Guardianes de deteccion/: pureza de imports (C-B5-5) y determinismo
(T-B5-13: prohibidos today/now/utcnow/random en todo el paquete)."""
import ast
import sys
import unittest
from pathlib import Path

PAQ = Path(__file__).resolve().parent.parent / "sibila" / "deteccion"

PROHIBIDOS = {"sqlite3", "requests", "random"}          # + nada no-stdlib
LLAMADAS_RELOJ = {"today", "now", "utcnow", "time", "monotonic", "perf_counter"}


class TestGuardianDeteccion(unittest.TestCase):
    def test_stdlib_puro(self):
        permitidos = set(sys.stdlib_module_names) | {"sibila"}
        for py in sorted(PAQ.glob("*.py")):
            arbol = ast.parse(py.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Import):
                    for a in nodo.names:
                        self.assertIn(a.name.split(".")[0], permitidos,
                                      f"{py.name} importa {a.name}")
                elif isinstance(nodo, ast.ImportFrom):
                    if nodo.level == 0 and nodo.module:
                        self.assertIn(nodo.module.split(".")[0], permitidos,
                                      f"{py.name} importa {nodo.module}")

    def test_sin_reloj_ni_aleatorio(self):
        for py in sorted(PAQ.glob("*.py")):
            arbol = ast.parse(py.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Attribute):
                    self.assertNotIn(nodo.attr, LLAMADAS_RELOJ,
                                     f"{py.name} usa reloj: .{nodo.attr}(")
                if isinstance(nodo, (ast.Import, ast.ImportFrom)):
                    nombres = ([a.name for a in nodo.names] if
                               isinstance(nodo, ast.Import) else
                               [nodo.module or ""])
                    for nm in nombres:
                        self.assertNotEqual(nm.split(".")[0], "random")

    def test_paquete_importable(self):
        for m in ("series", "cusum", "pendiente", "motor"):
            __import__(f"sibila.deteccion.{m}")


if __name__ == "__main__":
    unittest.main()

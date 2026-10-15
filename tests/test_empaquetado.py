"""T1 · empaquetado (plan Hopper §5, adaptado a sandbox Linux).
Nota de adaptación: el test de import limpio NO usa `python -I` (el modo aislado quita
el cwd de sys.path y el paquete no se encontraría); se usa cwd=raíz y verificación de
efectos laterales por snapshot del directorio. Sin PYTHONNOUSERSITE: las deps del
bloque 2 (feedparser, requests) viven en user-site del entorno, igual que en Hermes."""
import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _corre(args, cwd=RAIZ, env_extra=None):
    env = dict(os.environ)
    deps = RAIZ.parent / "deps"  # sandbox: $HOME efímero → deps en pip --target persistente
    if deps.is_dir():
        env["PYTHONPATH"] = str(deps) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, *args], cwd=cwd, env=env,
                          capture_output=True, text=True, errors="replace", timeout=120)
    # errors="replace": el hijo del test cp1252 emite bytes cp1252 (é=0xe9) que romperían
    # la decodificación UTF-8 del PADRE; el defecto era del arnés, no del programa.


class TestEmpaquetado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))

    def test_import_limpio_sin_efectos(self):
        def arbol():  # snapshot RECURSIVO (rev. Hamilton: el plano no basta)
            return {str(p.relative_to(RAIZ)) for p in RAIZ.rglob("*")
                    if "__pycache__" not in str(p)}
        antes = arbol()
        r = _corre(["-c", "import sibila, sibila.cli, sibila.config, sibila.db"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(arbol() - antes, set(),
                         "importar creó cosas (efectos laterales, trampa T11)")

    def test_ayuda_exit_0_lista_comandos(self):
        r = _corre(["-m", "sibila", "--help"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("init", r.stdout)
        self.assertIn("check", r.stdout)
        self.assertIn("doctor", r.stdout)

    def test_sin_argumentos_exit_2(self):
        r = _corre(["-m", "sibila"])
        self.assertEqual(r.returncode, 2)

    def test_stdlib_puro_ast(self):
        """Todo import raíz ∈ sys.stdlib_module_names ∪ {sibila, deps declaradas} (C5).
        rev. Hamilton M2: rglob — con glob plano los 6 módulos de sibila/conectores/
        quedaban FUERA del guardián de imports."""
        externos = set()
        escaneados = 0
        for carpeta in (RAIZ / "sibila", RAIZ / "tests"):
            for py in carpeta.rglob("*.py"):
                escaneados += 1
                arbol = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
                for nodo in ast.walk(arbol):
                    if isinstance(nodo, ast.Import):
                        externos |= {a.name.split(".")[0] for a in nodo.names}
                    elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                        externos.add(nodo.module.split(".")[0])
        # deps bloque 2 + "tests": test_reddit reutiliza SesionStub de tests.test_conectores_base
        permitidos = set(sys.stdlib_module_names) | {"sibila", "feedparser", "requests", "tests", "tools"}  # "tools": test_instalador importa tools/*.py (T2)
        self.assertEqual(externos - permitidos, set(),
                         f"imports no-stdlib: {externos - permitidos}")
        self.assertGreaterEqual(escaneados, 20,  # guardia del guardián: ¿se escaneó de verdad?
                                "el rglob no está cubriendo sibila/conectores/")

    def _env_sandbox(self, subdir):
        datos = self.tmp / subdir / "datos"
        return {"SIBILA_DATA_DIR": str(datos), "SIBILA_DB_PATH": str(datos / "sibila.db")}

    def test_consola_cp1252_proxy(self):
        """Proxy del cmd de Windows (PYTHONIOENCODING=cp1252): sin UnicodeError ni mojibake."""
        env = dict(self._env_sandbox("cp1252"), PYTHONIOENCODING="cp1252")
        r1 = _corre(["-m", "sibila", "init"], env_extra=env)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = _corre(["-m", "sibila", "check"], env_extra=env)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertNotIn("UnicodeEncodeError", r2.stderr)
        self.assertNotIn("Traceback", r2.stderr)

    def test_ruta_con_espacios_y_acentos(self):
        """Proxy del perfil C:\\Users\\José Pérez (el tmp de esta suite ya tiene ambos)."""
        env = self._env_sandbox("proyecto sibila")
        r1 = _corre(["-m", "sibila", "init"], env_extra=env)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = _corre(["-m", "sibila", "check"], env_extra=env)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertTrue((self.tmp / "proyecto sibila" / "datos" / "sibila.db").exists())


if __name__ == "__main__":
    unittest.main()

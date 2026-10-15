"""T2 · sibila/paquete.py + `sibila paquete` (plan §2.4, D-048).

Guardián de cobertura (rglob, suelo 70), integridad en repo, roturas
falta/hash/bytes, extras-no-rotura, determinismo con ahora fijo (H4),
secretos-nunca (mordida §2.4.10) y aceptación de directorio limpio (§3.2).
"""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sibila import paquete

RAIZ = Path(__file__).resolve().parent.parent
AHORA_FIJO = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def _arbol_tmp(test) -> Path:
    """Copia del árbol del paquete (sin __pycache__) en tmp con espacios."""
    tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
    test.addCleanup(shutil.rmtree, tmp, True)
    dst = tmp / "paq"
    shutil.copytree(RAIZ, dst,
                    ignore=shutil.ignore_patterns("__pycache__", "logs",
                                                  "datos", "*.db*"))
    return dst


class TestCobertura(unittest.TestCase):  # §2.4.1
    def test_manifiesto_cubre_todos_los_py(self):
        ruta = RAIZ / paquete.MANIFIESTO
        self.assertTrue(ruta.exists(), "MANIFIESTO.sha256.json ausente: "
                                       "ejecuta 'python -m sibila paquete generar'")
        m = json.loads(ruta.read_bytes())
        self.assertGreater(len(m["ficheros"]), 0)
        en_manifiesto = {f["ruta"] for f in m["ficheros"]}
        # conjunto real de .py bajo sibila/, tests/, tools/ (si existe) + resumen.py
        reales = set()
        for base in ("sibila", "tests", "tools"):
            d = RAIZ / base
            if d.exists():                       # tools/ puede no existir (§1.4b)
                for p in d.rglob("*.py"):
                    if "__pycache__" not in p.parts:
                        reales.add(p.relative_to(RAIZ).as_posix())
        if (RAIZ / "resumen.py").exists():
            reales.add("resumen.py")
        self.assertGreaterEqual(len(reales), 70)   # guardia del guardián (H6: 89 hoy)
        self.assertEqual(en_manifiesto & reales, reales,
                         f"sin cobertura: {sorted(reales - en_manifiesto)}")
        # viajeros no-.py de §1.4b presentes en disco deben estar cubiertos
        for patron in ("*.bat", "*.xml"):
            for p in RAIZ.glob(patron):
                self.assertIn(p.name, en_manifiesto, f"{p.name} viaja y no está")
        for p in (RAIZ / "tools").glob("*.py") if (RAIZ / "tools").exists() else []:
            self.assertIn(p.relative_to(RAIZ).as_posix(), en_manifiesto)
        # canonical_json: lista ordenada por ruta POSIX (orden de bytes)
        rutas = [f["ruta"] for f in m["ficheros"]]
        self.assertEqual(rutas, sorted(rutas))
        self.assertEqual(m["generador"], "sibila-paquete-1")

    def test_version_programa_null_o_forma_d019(self):
        m = json.loads((RAIZ / paquete.MANIFIESTO).read_bytes())
        self.assertIn("version_programa", m)     # la clave EXISTE
        v = m["version_programa"]
        if v is not None:
            import re
            self.assertRegex(v, r"^\d+\.\d+[A-Z]?$")   # forma D-019, sin fijar valor


class TestIntegridadRepo(unittest.TestCase):  # §2.4.2
    def test_manifiesto_integro_en_repo(self):
        roturas = paquete.verificar(RAIZ)
        self.assertEqual(roturas, [], "manifiesto obsoleto: regenera con "
                         "'python -m sibila paquete generar' tras editar código")


class TestRoturas(unittest.TestCase):  # §2.4.3-2.4.6 en copia tmp
    def setUp(self):
        self.dst = _arbol_tmp(self)
        paquete.escribir(self.dst, ahora=AHORA_FIJO)

    def test_rotura_detectada(self):
        victima = self.dst / "sibila" / "__init__.py"
        datos = bytearray(victima.read_bytes())
        datos[0] ^= 0xFF
        victima.write_bytes(bytes(datos))
        self.assertEqual(paquete.verificar(self.dst),
                         ["hash: sibila/__init__.py"])

    def test_falta_detectada(self):
        (self.dst / "resumen.py").unlink()
        self.assertEqual(paquete.verificar(self.dst), ["falta: resumen.py"])

    def test_extra_no_es_rotura(self):           # árbol VIVIDO (H1)
        (self.dst / "logs").mkdir(exist_ok=True)
        (self.dst / "logs" / "x.log").write_text("ruido", encoding="utf-8")
        (self.dst / "datos").mkdir(exist_ok=True)
        (self.dst / "datos" / "sibila.db").write_bytes(b"bd local")
        (self.dst / "registro").mkdir(exist_ok=True)
        (self.dst / "registro" / "predicciones.jsonl").write_bytes(b"{}\n")
        (self.dst / "config.local.toml").write_text('telegram_token = "secreto"')
        self.assertEqual(paquete.verificar(self.dst), [])

    def test_bytes_redundante(self):             # bytes Y hash, ambas clases
        victima = self.dst / "resumen.py"
        datos = victima.read_bytes()
        victima.write_bytes(datos[:len(datos) // 2])
        self.assertEqual(sorted(paquete.verificar(self.dst)),
                         ["bytes: resumen.py", "hash: resumen.py"])

    def test_dos_roturas_ambas_reportadas_en_orden(self):  # doctrina: TODAS
        """return-early es rotura de doctrina (registro/verificar): con dos
        ficheros rotos, ambas roturas aparecen, en orden de ruta."""
        v1 = self.dst / "resumen.py"
        d1 = bytearray(v1.read_bytes()); d1[0] ^= 1; v1.write_bytes(bytes(d1))
        v2 = self.dst / "sibila" / "__init__.py"
        d2 = bytearray(v2.read_bytes()); d2[0] ^= 1; v2.write_bytes(bytes(d2))
        roturas = paquete.verificar(self.dst)
        self.assertEqual(roturas, ["hash: resumen.py", "hash: sibila/__init__.py"])

    def test_manifiesto_ausente_es_rotura(self):
        (self.dst / paquete.MANIFIESTO).unlink()
        self.assertEqual(paquete.verificar(self.dst),
                         [f"falta: {paquete.MANIFIESTO}"])


class TestDeterminismo(unittest.TestCase):  # §2.4.7/8 · H4
    def test_generar_determinista_con_ahora_fijo(self):
        dst = _arbol_tmp(self)
        a = paquete.generar(dst, ahora=AHORA_FIJO)
        b = paquete.generar(dst, ahora=AHORA_FIJO)
        self.assertEqual(a, b)
        self.assertTrue(a.endswith(b"\n"))           # convención registro sellado
        self.assertNotIn(b"\r\n", a)
        # canonical_json tal cual: sin espacios, claves ordenadas
        self.assertTrue(a.startswith(b'{"ficheros":'))
        self.assertIn(b'"generado":"2026-09-10T12:00:00Z"', a)
        # el ORDEN POSIX viaja en los bytes generados (cazador de M3)
        rutas = [f["ruta"] for f in json.loads(a)["ficheros"]]
        self.assertEqual(rutas, sorted(rutas))
        self.assertGreater(len(rutas), 70)

    def test_regenerado_igual_a_disco(self):
        """Con el `generado` leído del manifiesto en disco, regenerar es
        byte-idéntico (sin reloj colándose, canonical_json anclado)."""
        dst = _arbol_tmp(self)
        paquete.escribir(dst, ahora=AHORA_FIJO)
        en_disco = (dst / paquete.MANIFIESTO).read_bytes()
        generado = json.loads(en_disco)["generado"]
        self.assertEqual(paquete.generar(dst, ahora=generado), en_disco)


class TestSecretos(unittest.TestCase):  # §2.4.10 · mordida incluida
    def test_secretos_nunca_en_manifiesto(self):
        dst = _arbol_tmp(self)
        (dst / "config.local.toml").write_text(
            'telegram_token = "SECRETO_12345"\n', encoding="utf-8")
        rutas = [p.as_posix() for p in paquete.inventario(dst)]
        self.assertNotIn("config.local.toml", rutas)
        datos = paquete.generar(dst, ahora=AHORA_FIJO)
        # ni la ruta del fichero real ni su CONTENIDO pueden colarse
        self.assertNotIn(b"SECRETO_12345", datos)
        for entrada in json.loads(datos)["ficheros"]:
            self.assertNotEqual(Path(entrada["ruta"]).name, "config.local.toml")
        # nota: "config.local.toml.example" SÍ viaja (§1.2) — la exclusión de
        # secretos es por PREFIJO (rev. Dijkstra M4), no por subcadena.

    def test_bak_de_secretos_no_viaja(self):  # rev. Dijkstra M4
        # La exclusión por nombre exacto dejaba colar "config.local.toml.bak"
        # (una copia de respaldo CON credenciales). Regla: prefijo
        # config.local.toml* fuera; la plantilla .example SÍ entra.
        dst = _arbol_tmp(self)
        (dst / "config.local.toml.bak").write_text(
            'telegram_token = "SECRETO_BAK"\n', encoding="utf-8")
        (dst / "config.local.toml.tmp").write_text(
            'telegram_token = "SECRETO_TMP"\n', encoding="utf-8")
        (dst / "config.local.toml.example").write_text(
            'telegram_token = "PON_AQUI"\n', encoding="utf-8")
        rutas = {p.as_posix() for p in paquete.inventario(dst)}
        self.assertNotIn("config.local.toml.bak", rutas)
        self.assertNotIn("config.local.toml.tmp", rutas)
        self.assertIn("config.local.toml.example", rutas)
        datos = paquete.generar(dst, ahora=AHORA_FIJO)
        self.assertNotIn(b"SECRETO_BAK", datos)
        self.assertNotIn(b"SECRETO_TMP", datos)


class TestAceptacion(unittest.TestCase):  # §3.2 corregida (H5)
    """Directorio limpio → init → check VERDE → ingesta --fuente lobsters
    --fixture <ruta> → procesa → sonda bot_detector_version → idempotencia →
    paquete verificar en vivo."""

    def _run(self, cwd, *argv):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(RAIZ)
        return subprocess.run(
            [_sys.executable, "-m", "sibila", *argv], cwd=cwd, env=env,
            capture_output=True, text=True, timeout=180)

    def test_aceptacion_directorio_limpio(self):
        tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        self.addCleanup(shutil.rmtree, tmp, True)
        # bootstrap del sandbox (D-032): feedparser y cía viven en ../deps
        # (misma técnica que el preámbulo de los tests); en destino los cubre
        # el instalador (INTERFAZ CON PLAN HOPPER)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(RAIZ),
                                             str(RAIZ.parent / "deps")])
        env["SIBILA_DB_PATH"] = str(tmp / "sibila.db")
        env["SIBILA_DATA_DIR"] = str(tmp / "datos")

        def run(*argv):
            return subprocess.run([_sys.executable, "-m", "sibila", *argv],
                                  cwd=tmp, env=env, capture_output=True,
                                  text=True, timeout=180)
        r = run("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((tmp / "sibila.db").exists())
        import sqlite3
        uv = sqlite3.connect(tmp / "sibila.db").execute(
            "PRAGMA user_version").fetchone()[0]
        self.assertEqual(uv, 1)

        r = run("check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("VERDE", r.stdout)

        fixture = RAIZ / "tests" / "fixtures" / "conectores" / "lobsters.xml"
        r = run("ingesta", "--fuente", "lobsters", "--fixture", str(fixture))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("3 nuevos, 0 duplicados, 0 errores", r.stdout)

        r = run("procesa")
        self.assertEqual(r.returncode, 0, r.stderr)
        con = sqlite3.connect(tmp / "sibila.db")
        n = con.execute(
            "SELECT COUNT(*) FROM documents WHERE calidad_score IS NOT NULL"
            " AND bot_detector_version IS NOT NULL").fetchone()[0]  # D-B4-05
        self.assertEqual(n, 3)
        con.close()

        r = run("procesa")                            # idempotencia TP-N8
        self.assertEqual(r.returncode, 0)
        self.assertIn("sin documentos pendientes", r.stdout)

        r = run("paquete", "verificar")               # manifiesto en vivo
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ÍNTEGRO", r.stdout)


class TestPaqueteCli(unittest.TestCase):  # §2.4.9
    def _run(self, cwd, *argv, pythonpath=None):
        env = dict(os.environ, PYTHONPATH=str(pythonpath or RAIZ))
        return subprocess.run([_sys.executable, "-m", "sibila", *argv],
                              cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=60)

    def test_verificar_repo_exit_0(self):
        r = self._run(RAIZ, "paquete", "verificar")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\[OK\] paquete ÍNTEGRO \(\d+ ficheros\)")

    def test_verificar_copia_rota_exit_1(self):
        # el paquete verificado es el que RESUELVE el import (raíz del paquete
        # = padre de sibila/); por eso el subprocess carga sibila desde la copia
        dst = _arbol_tmp(self)
        paquete.escribir(dst, ahora=AHORA_FIJO)
        victima = dst / "sibila" / "__init__.py"
        victima.write_bytes(victima.read_bytes() + b"# rotura\n")
        r = self._run(dst, "paquete", "verificar", pythonpath=dst)
        self.assertEqual(r.returncode, 1)
        self.assertIn("[FALLO] paquete: hash: sibila/__init__.py", r.stderr)


if __name__ == "__main__":
    unittest.main()

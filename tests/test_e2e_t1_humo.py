"""T1 (D-047): humo de SUPERFICIE de la cadena CLI en SUBPROCESO real.

init → check → ingesta(fixture lobsters) → procesa → detecta → registro
sellar → registro verificar → informe --salida → alerta digest.
Sin vectores ni cooldowns inter-día (eso es la parte Turing). CERO líneas de
producción: este módulo es solo test.

Aislamiento: SIBILA_DATA_DIR/SIBILA_DB_PATH en tmp con acentos y espacios
(T-11), cwd ≠ raíz del repo, PYTHONPATH = deps + repo (feedparser no es
system-wide). Corpus: fixture lobsters existente (D-047 retiró el generador).
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPS = REPO.parent / "deps"
FIXTURE = REPO / "tests" / "fixtures" / "conectores" / "lobsters.xml"
FUENTES = REPO / "tests" / "fuentes_test.toml"


def _entorno(data_dir: Path) -> dict:
    env = dict(os.environ)
    env["SIBILA_DATA_DIR"] = str(data_dir)
    env["SIBILA_DB_PATH"] = str(data_dir / "sibila.db")
    env["PYTHONPATH"] = os.pathsep.join([str(DEPS), str(REPO)])
    env.pop("SIBILA_TELEGRAM_TOKEN", None)      # humo SIN credenciales (A8)
    env.pop("SIBILA_TELEGRAM_CHAT_ID", None)
    env.pop("SIBILA_SMTP", None)
    return env


def _sibila(args: list, data_dir: Path, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "sibila"] + args,
                          capture_output=True, text=True, env=_entorno(data_dir),
                          cwd=str(cwd), timeout=120)


class HumoBase:
    """Monta una cadena completa en un tmp propio (una vez por clase)."""

    @classmethod
    def preparar(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="sibila José Pérez T1 ")
        raiz = Path(cls._tmp.name)
        cls.data = raiz / "datos"
        cls.cwd = raiz / "cwd"          # cwd ≠ repo (independencia de rutas)
        cls.cwd.mkdir()
        cls.resultados = {}
        return raiz

    @classmethod
    def limpiar(cls):
        cls._tmp.cleanup()

    def cli(self, *args):
        return _sibila(list(args), self.data, self.cwd)


class TestCadenaSuperficie(HumoBase, unittest.TestCase):
    """La cadena entera, paso a paso, con exit codes y marcas [OK]."""

    @classmethod
    def setUpClass(cls):
        raiz = cls.preparar()
        cls.resultados["init"] = cls().cli("init")
        cls.resultados["check"] = cls().cli("check")
        cls.resultados["ingesta"] = cls().cli(
            "ingesta", "--fuentes", str(FUENTES), "--fuente", "lobsters",
            "--fixture", str(FIXTURE))
        cls.resultados["procesa"] = cls().cli("procesa")
        cls.resultados["detecta"] = cls().cli("detecta")
        cls.resultados["sellar"] = cls().cli("registro", "sellar")
        cls.resultados["verificar"] = cls().cli("registro", "verificar")
        cls.informe_md = raiz / "informe.md"
        cls.resultados["informe"] = cls().cli("informe", "--salida",
                                              str(cls.informe_md))
        cls.resultados["digest"] = cls().cli("alerta", "digest")

    @classmethod
    def tearDownClass(cls):
        cls.limpiar()

    def test_init(self):
        r = self.resultados["init"]
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[OK]", r.stdout)

    def test_check(self):
        r = self.resultados["check"]
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[OK]", r.stdout)

    def test_ingesta_fixture(self):
        r = self.resultados["ingesta"]
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[OK]", r.stdout)
        self.assertIn("nuevos", r.stdout)

    def test_procesa(self):
        r = self.resultados["procesa"]
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[OK]", r.stdout)

    def test_detecta(self):
        r = self.resultados["detecta"]
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[OK]", r.stdout)

    def test_registro_sellar(self):
        r = self.resultados["sellar"]
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[OK]", r.stdout)

    def test_registro_verificar(self):
        r = self.resultados["verificar"]
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ÍNTEGRO", r.stdout)

    def test_informe_salida(self):
        r = self.resultados["informe"]
        self.assertEqual(r.returncode, 0, r.stderr)
        txt = self.informe_md.read_text(encoding="utf-8")
        self.assertTrue(txt.startswith("[OK] informe:"))
        for cab in ("== Resumen ==", "== Tension ==", "== Emergentes ==",
                    "== Alertas ==", "== Anomalias ==", "== Predicciones ==",
                    "== Exportacion =="):
            self.assertIn(cab, txt)

    def test_digest_sin_credenciales(self):
        r = self.resultados["digest"]
        self.assertEqual(r.returncode, 0, r.stderr)   # digest degradado, no crash


class TestChoqueRegistro(HumoBase, unittest.TestCase):
    """Choque §5-1 sobre una cadena REAL (señal sintética → registro sellar):
    manipulación a mitad de línea → verificar ROTO exit 1; cola coja (crash
    truncando la ÚLTIMA línea) → AVISO pero ÍNTEGRO (tolerancia a crash)."""

    @classmethod
    def setUpClass(cls):
        cls.preparar()
        assert cls().cli("init").returncode == 0
        # Señal confirmada de ayer → sellar escribe jsonl + predictions
        # consistentes (el cruce fichero↔tabla exige coherencia).
        import sqlite3
        from datetime import datetime, timedelta, timezone
        # MED-1 resuelta (D-077): sellar sin --dia toma ayer UTC; la señal
        # debe fecharse en UTC para que el cruce sea coherente con cualquier TZ
        ayer = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        con = sqlite3.connect(cls.data / "sibila.db")
        con.execute("INSERT INTO terms(text, type) VALUES('terremoto','term')")
        con.execute("INSERT INTO signals(day, target_type, target_id, metric,"
                    " score, status, created_at) VALUES(?, 'term', 1, 'z_r',"
                    " 6.745, 'confirmado', ?)", (ayer, ayer + "T00:00:00Z"))
        con.commit()
        con.close()
        r = cls().cli("registro", "sellar")
        assert r.returncode == 0 and "1 predicciones selladas" in r.stdout, r.stdout
        cls.fichero = cls.data / "registro" / "predicciones.jsonl"
        cls.original = cls.fichero.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.limpiar()

    def test_cadena_real_integro(self):
        self.fichero.write_bytes(self.original)
        r = self.cli("registro", "verificar")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ÍNTEGRO", r.stdout)

    def test_manipulacion_mitad_de_linea_es_rotura(self):
        datos = bytearray(self.original)
        i = datos.find(b"terremoto")
        datos[i:i + 3] = b"XXX"          # edición que descuadra el hash
        self.fichero.write_bytes(bytes(datos))
        r = self.cli("registro", "verificar")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("ROTO", r.stdout)
        self.assertIn("[FALLO]", r.stdout)

    def test_cola_coja_es_aviso_no_rotura(self):
        # crash escribiendo la SIGUIENTE línea a mitad (la cadena completa y
        # la BD quedan coherentes): tolerado con AVISO, sigue ÍNTEGRO
        self.fichero.write_bytes(self.original + b'{"tema":"trunc')
        r = self.cli("registro", "verificar")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("cola incompleta", r.stdout)


class TestChoqueCadenaIncompleta(HumoBase, unittest.TestCase):
    """Choque §5-2: la cadena se detiene a mitad (crash) y se reanuda."""

    @classmethod
    def setUpClass(cls):
        cls.preparar()

    @classmethod
    def tearDownClass(cls):
        cls.limpiar()

    def test_reanudacion_tras_parada(self):
        self.assertEqual(self.cli("init").returncode, 0)
        r = self.cli("ingesta", "--fuentes", str(FUENTES), "--fuente",
                     "lobsters", "--fixture", str(FIXTURE))
        self.assertEqual(r.returncode, 0)
        # "Crash": la cadena para aquí. Reanudación:
        for cmd in (["procesa"], ["detecta"], ["registro", "sellar"],
                    ["registro", "verificar"]):
            r = self.cli(*cmd)
            self.assertEqual(r.returncode, 0, f"{cmd}: {r.stderr}")


if __name__ == "__main__":
    unittest.main()

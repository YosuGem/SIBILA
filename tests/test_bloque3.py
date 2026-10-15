"""T1 · Bloque 3 (Hermes T2): cambios C1 (descanso entre fuentes de red),
C2 (log rotativo 1 MB × 3 en UTC) y C3 (resumen.py de solo lectura).
Cada test muerde la mutación: sin el cambio, el test falla."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
_raiz = _P(__file__).resolve().parent.parent  # resumen.py vive en la raíz del repo

import contextlib
import importlib.util
import io
import logging
import os
import sqlite3
import tempfile
import time
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sibila import cli, db
from sibila import conectores as conectores_mod


def _cargar_resumen():
    """Carga resumen.py POR RUTA (importlib): un `import resumen` añadiría una raíz
    no-stdlib al guardián AST de test_empaquetado (C5)."""
    spec = importlib.util.spec_from_file_location("resumen_b3", _raiz / "resumen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


resumen = _cargar_resumen()

UTC_T = "%Y-%m-%dT%H:%M:%SZ"


# ------------------------------------------------------------------ C1 · dormir

class _Fake:
    """Fuente falsa: cfg sin 'fixture' = red; fetch vacío, cursor sin cambios."""
    def __init__(self, cfg, nombre):
        self.cfg, self.nombre = cfg, nombre
    def fetch(self, cfg, cursor, **kw):
        return [], cursor


class TestC1DescansoEntreFuentes(unittest.TestCase):
    """dormir(2.0) exactamente n-1 veces SOLO entre fuentes de red y SOLO con DB."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._env = dict(os.environ)
        os.environ["SIBILA_DATA_DIR"] = str(self.tmp)
        os.environ["SIBILA_DB_PATH"] = str(self.tmp / "c1.db")
        db.init_db(self.tmp / "c1.db")
        self.registro_original = dict(conectores_mod.REGISTRO)

    def tearDown(self):
        conectores_mod.REGISTRO.clear()
        conectores_mod.REGISTRO.update(self.registro_original)
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def _monta(self, nombres, con_fixture=False) -> Path:
        """Alta REAL en sources + REGISTRO falso + fuentes.toml temporal."""
        con = db.connect(self.tmp / "c1.db")
        try:
            for n in nombres:
                con.execute("INSERT OR IGNORE INTO sources(nombre, tipo, idioma)"
                            " VALUES (?, 'test', 'es')", (n,))
            con.commit()
        finally:
            con.close()
        conectores_mod.REGISTRO.clear()
        conectores_mod.REGISTRO.update(
            {n: (lambda cfg, n=n: _Fake(cfg, n)) for n in nombres})
        lineas = []
        for n in nombres:
            lineas.append(f"[{n}]\n")
            if con_fixture:
                lineas.append("fixture = \"f.json\"\n")
        (self.tmp / "f.json").write_text("{}", encoding="utf-8")
        ruta = self.tmp / "fuentes_c1.toml"
        ruta.write_text("".join(lineas), encoding="utf-8")
        return ruta

    def _corre(self, ruta_toml: Path, sin_db: bool):
        argv = ["ingesta", "--fuentes", str(ruta_toml)]
        if sin_db:
            argv.append("--sin-db")
        args = cli._build_parser().parse_args(argv)
        llamadas = []
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli._cmd_ingesta(args, dormir=lambda s: llamadas.append(s))
        return rc, llamadas

    def test_dos_fuentes_red_un_descanso(self):
        ruta = self._monta(["aa", "bb"])
        rc, llamadas = self._corre(ruta, sin_db=False)
        self.assertEqual(rc, 0)
        self.assertEqual(llamadas, [2.0])  # n-1 = 1, y de 2 segundos

    def test_tres_fuentes_red_dos_descansos(self):
        ruta = self._monta(["aa", "bb", "cc"])
        rc, llamadas = self._corre(ruta, sin_db=False)
        self.assertEqual(rc, 0)
        self.assertEqual(llamadas, [2.0, 2.0])  # n-1 = 2

    def test_fixtures_cero_descansos(self):
        ruta = self._monta(["aa", "bb"], con_fixture=True)
        rc, llamadas = self._corre(ruta, sin_db=False)
        self.assertEqual(rc, 0)
        self.assertEqual(llamadas, [])  # fixtures: nunca hay descanso

    def test_red_y_luego_fixture_cero_descansos(self):
        """rev. Hamilton M3 r3: el descanso es ENTRE dos fuentes de red; red→fixture
        no molesta a ningún servidor (la fixture no hace red)."""
        (self.tmp / "fuentes_c1.toml").write_text(
            "[aa]\n[bb]\nfixture = \"f.json\"\n", encoding="utf-8")
        (self.tmp / "f.json").write_text("{}", encoding="utf-8")
        con = db.connect(self.tmp / "c1.db")
        try:
            for n in ("aa", "bb"):
                con.execute("INSERT OR IGNORE INTO sources(nombre, tipo, idioma)"
                            " VALUES (?, 'test', 'es')", (n,))
            con.commit()
        finally:
            con.close()
        conectores_mod.REGISTRO.clear()
        conectores_mod.REGISTRO.update(
            {n: (lambda cfg, n=n: _Fake(cfg, n)) for n in ("aa", "bb")})
        rc, llamadas = self._corre(self.tmp / "fuentes_c1.toml", sin_db=False)
        self.assertEqual(rc, 0)
        self.assertEqual(llamadas, [])  # aa es red pero bb NO: 0 descansos

    def test_sin_db_cero_descansos(self):
        ruta = self._monta(["aa", "bb"])
        rc, llamadas = self._corre(ruta, sin_db=True)
        self.assertEqual(rc, 0)
        self.assertEqual(llamadas, [])  # --sin-db: cortesía innecesaria, nada duerme


# ------------------------------------------------------------------ C2 · log rotativo

class TestC2LogRotativoUtc(unittest.TestCase):
    """El handler debe ser RotatingFileHandler 1 MB × 3 con sellos en UTC."""

    def setUp(self):
        self.raiz_log = logging.getLogger("sibila")
        self._handlers = list(self.raiz_log.handlers)
        for h in self._handlers:
            self.raiz_log.removeHandler(h)

    def tearDown(self):
        for h in list(self.raiz_log.handlers):
            self.raiz_log.removeHandler(h)
            h.close()
        for h in self._handlers:
            self.raiz_log.addHandler(h)

    def test_handler_rotativo_1mb_por_3_en_utc(self):
        cli._configurar_logging()
        handlers = [h for h in self.raiz_log.handlers
                    if isinstance(h, RotatingFileHandler)]
        self.assertEqual(len(handlers), 1, "debe haber exactamente un RotatingFileHandler")
        h = handlers[0]
        self.assertEqual(h.maxBytes, 1_000_000)     # mutación 1 MB → 10 MB muerde aquí
        self.assertEqual(h.backupCount, 3)          # mutación 3 → 1 muerde aquí
        self.assertTrue(h.baseFilename.endswith("sibila.log"))
        self.assertIs(h.formatter.converter, time.gmtime)  # UTC, no hora local

    def test_no_duplica_handlers_si_se_llama_dos_veces(self):
        cli._configurar_logging()
        cli._configurar_logging()
        self.assertEqual(len(self.raiz_log.handlers), 1)


# ------------------------------------------------------------------ C3 · resumen.py

def _ahora_z() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime(UTC_T)


def _ayer_z() -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=48)).strftime(UTC_T)


class TestC3Resumen(unittest.TestCase):
    """resumen.py: agregados de 24 h, dups = url + contenido, cruce de fuentes
    ausentes (rev. Hamilton N1), URI escapada (rev. Dijkstra B2), avisos y exit codes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "r.db"
        db.init_db(self.db_path)
        self._env = dict(os.environ)
        os.environ["SIBILA_DB_PATH"] = str(self.db_path)
        # El cruce de fuentes NO usa el fuentes.toml real del repo (rev. N1):
        # cada test decide qué fuentes están habilitadas
        self.fuentes_toml = self.tmp / "fuentes_resumen.toml"
        self._pon_fuentes(["reddit", "mastodon"])
        self._ruta_original = resumen._ruta_fuentes
        resumen._ruta_fuentes = lambda: self.fuentes_toml

    def tearDown(self):
        resumen._ruta_fuentes = self._ruta_original
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def _pon_fuentes(self, nombres):
        self.fuentes_toml.write_text(
            "".join(f"[{n}]\n" for n in nombres), encoding="utf-8")

    def _mete(self, clave, valor, ts):
        con = db.connect(self.db_path)
        try:
            con.execute("INSERT INTO ops_metrics(ts, clave, valor) VALUES (?,?,?)",
                        (ts, clave, valor))
            con.commit()
        finally:
            con.close()

    def _corre(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = resumen.main()
        return rc, out.getvalue(), err.getvalue()

    def test_agregados_24h_y_exit_0(self):
        ahora = _ahora_z()
        self._mete("ingesta.nuevos.reddit", 5, ahora)
        self._mete("ingesta.nuevos.reddit", 3, ahora)      # se SUMAN: 8
        self._mete("ingesta.duplicados_url.reddit", 2, ahora)
        self._mete("ingesta.duplicados_contenido.reddit", 1, ahora)  # dups = 2+1 = 3
        self._mete("ingesta.errores.mastodon", 4, ahora)
        self._mete("ingesta.nuevos.reddit", 99, _ayer_z())  # fuera de ventana: NO cuenta
        rc, out, err = self._corre()
        self.assertEqual(rc, 0)
        self.assertIn("reddit: 8 nuevos · 3 duplicados · 0 errores", out)
        self.assertIn("mastodon: 0 nuevos · 0 duplicados · 4 errores", out)
        self.assertIn("documents total: 0", out)
        self.assertNotIn("99", out)
        self.assertEqual(err, "")

    def test_ventana_24h_exacta(self):
        """rev. Dijkstra M2: una fila de 13 h DEBE contar (la mutación 24 h→12 h muere)."""
        from datetime import datetime, timedelta, timezone
        hace13 = (datetime.now(timezone.utc) - timedelta(hours=13)).strftime(UTC_T)
        self._mete("ingesta.nuevos.reddit", 7, hace13)
        self._mete("ingesta.nuevos.mastodon", 1, hace13)
        rc, out, _ = self._corre()
        self.assertEqual(rc, 0)
        self.assertIn("reddit: 7 nuevos", out)

    def test_fuente_sin_actividad_aviso_y_exit_1(self):
        """rev. Hamilton N1: una fuente caída no escribe métricas; si no se cruzara
        con fuentes.toml desaparecería del ritual (verde falso)."""
        self._mete("ingesta.nuevos.reddit", 5, _ahora_z())  # mastodon: NADA
        rc, out, err = self._corre()
        self.assertEqual(rc, 1)
        self.assertIn("[AVISO] mastodon: sin actividad en las últimas 24 h", out)
        self.assertIn("reddit: 5 nuevos", out)

    def test_fuente_deshabilitada_no_se_exige(self):
        self._mete("ingesta.nuevos.reddit", 5, _ahora_z())
        self.fuentes_toml.write_text(
            "[reddit]\n[mastodon]\nhabilitada = false\n", encoding="utf-8")
        rc, out, _ = self._corre()
        self.assertEqual(rc, 0)
        self.assertNotIn("sin actividad", out)

    def test_fuentes_toml_ilegible_degrada_sin_romper(self):
        """rev. Dijkstra M1-r2: si fuentes.toml no se puede leer, el ritual SIGUE
        (aviso por stderr, cruce omitido); la mutación except→raise muere aquí."""
        self.fuentes_toml.write_text("[reddit\nesto no es toml", encoding="utf-8")
        self._mete("ingesta.nuevos.reddit", 5, _ahora_z())
        rc, out, err = self._corre()
        self.assertEqual(rc, 0)               # el ritual no se rompe
        self.assertIn("reddit: 5 nuevos", out)
        self.assertIn("[AVISO] no se pudo leer", err)
        self.assertNotIn("sin actividad", out)  # cruce omitido, no falso aviso

    def test_sin_ingesta_reciente_aviso_y_exit_1(self):
        self._pon_fuentes(["reddit"])
        self._mete("ingesta.nuevos.reddit", 7, _ayer_z())  # solo actividad vieja
        rc, out, err = self._corre()
        self.assertEqual(rc, 1)
        self.assertIn("[AVISO] no hubo ingesta en las últimas 24 h", out)

    def test_base_inexistente_fallo_y_exit_1(self):
        os.environ["SIBILA_DB_PATH"] = str(self.tmp / "no_existe.db")
        rc, out, err = self._corre()
        self.assertEqual(rc, 1)
        self.assertIn("[FALLO]", err)

    def test_solo_lectura_no_crea_la_base(self):
        fantasma = self.tmp / "fantasma.db"
        os.environ["SIBILA_DB_PATH"] = str(fantasma)
        self._corre()
        self.assertFalse(fantasma.exists(),
                         "resumen.py NUNCA crea la base (mode=ro de verdad)")

    def test_ruta_con_espacio_y_almohadilla(self):
        """rev. Dijkstra B2: sin as_uri() la ruta con '#' abriría OTRA base
        (silenciosamente) en vez de la real."""
        rara = self.tmp / "carpeta rara #1"
        rara.mkdir()
        db_rara = rara / "sibila.db"
        db.init_db(db_rara)
        os.environ["SIBILA_DB_PATH"] = str(db_rara)
        self._pon_fuentes(["reddit"])
        con = db.connect(db_rara)
        try:
            con.execute("INSERT INTO ops_metrics(ts, clave, valor) VALUES (?,?,?)",
                        (_ahora_z(), "ingesta.nuevos.reddit", 6.0))
            con.commit()
        finally:
            con.close()
        rc, out, err = self._corre()
        self.assertEqual(rc, 0, err)
        self.assertIn("reddit: 6 nuevos", out)

    def test_timeout_30_en_la_conexion(self):
        """rev. Hamilton/Dijkstra M1: la corrección Liskov 1 (busy_timeout POR CONEXIÓN)
        debe quedar asertada; la mutación timeout=30→0 muere aquí."""
        import unittest.mock as _mock
        self._mete("ingesta.nuevos.reddit", 1, _ahora_z())
        self._mete("ingesta.nuevos.mastodon", 1, _ahora_z())
        capturado = {}
        real_connect = resumen.sqlite3.connect
        def espia(dsn, **kw):
            capturado.update(kw)
            capturado["dsn"] = dsn
            return real_connect(dsn, **kw)
        with _mock.patch.object(resumen.sqlite3, "connect", espia):
            rc, _, _ = self._corre()
        self.assertEqual(rc, 0)
        self.assertEqual(capturado["timeout"], 30)
        self.assertTrue(capturado["dsn"].endswith("?mode=ro"))


if __name__ == "__main__":
    unittest.main()

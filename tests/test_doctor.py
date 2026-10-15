"""Tests de doctor (T2, D-048 §3): subcomando nuevo de comprobación
post-instalación. D1-D6, mode=ro (la BD NUNCA se abre en escritura), "12
tablas" literal, git/ots AVISO nunca FALLO, centinela SIN_LINGUA."""
import importlib.util
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPS = REPO.parent / "deps"

sys.path.insert(0, str(REPO))

from sibila import config, db, doctor as doc_mod  # noqa: E402


def _cfg(tmp: Path):
    env = os.environ.copy()
    env["SIBILA_DATA_DIR"] = str(tmp / "datos")
    env["SIBILA_DB_PATH"] = str(tmp / "datos" / "sibila.db")
    return env


def _cli_doctor(tmp: Path, extra_env=None):
    env = _cfg(tmp)
    env["PYTHONPATH"] = os.pathsep.join([str(DEPS), str(REPO)])
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, "-m", "sibila", "doctor"],
                          capture_output=True, text=True, env=env, cwd=tmp)


class TestDoctorModulo(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        (self.tmp / "datos").mkdir()
        os.environ["SIBILA_DATA_DIR"] = str(self.tmp / "datos")
        os.environ["SIBILA_DB_PATH"] = str(self.tmp / "datos" / "sibila.db")
        self.cfg = config.load_config()

    def tearDown(self):
        if hasattr(self, "_dep_real"):
            doc_mod._dep = self._dep_real
        self._t.cleanup()

    def _parchea_deps(self):
        self._dep_real = doc_mod._dep
        doc_mod._dep = lambda nombre: True

    def _init_db(self):
        self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
        db.init_db(self.cfg.db_path)

    def test_sano_con_db_y_sin_recursos(self):
        self._parchea_deps()
        self._init_db()
        fallos, avisos, lineas = doc_mod.doctor(self.cfg)
        self.assertEqual(fallos, 0, lineas)
        self.assertIn("12 tablas", str(lineas))          # literal D1
        self.assertTrue(any("modo degradado" in m for e, m in lineas
                            if e == "AVISO"))            # D3 ausentes → AVISO
        self.assertIn("SANO", doc_mod.resumen(fallos, avisos))

    def test_sin_db_es_fallo_d1(self):
        fallos, _, lineas = doc_mod.doctor(self.cfg)
        self.assertGreaterEqual(fallos, 1)
        self.assertTrue(any("base de datos ausente" in m
                            for e, m in lineas if e == "FALLO"))

    def test_bd_no_se_abre_en_escritura(self):
        self._parchea_deps()
        # mode=ro: doctor con la BD bloqueada en escritura por OTRO no falla
        self._init_db()
        con = sqlite3.connect(self.cfg.db_path)
        con.execute("BEGIN IMMEDIATE")
        try:
            fallos, _, _ = doc_mod.doctor(self.cfg)
            self.assertEqual(fallos, 0)
        finally:
            con.rollback()
            con.close()

    def test_data_dir_con_alarabilla_no_rompe_uri_ro(self):  # rev. Dijkstra B1
        # Ruta con '#' (y espacio): el URI mode=ro va escapado con as_uri();
        # sin escapar, sqlite abre OTRO fichero vacío y doctor reporta FALLOs
        # espurios en una instalación correcta.
        self._parchea_deps()
        nuevo = self.tmp / "datos #alz"
        os.environ["SIBILA_DATA_DIR"] = str(nuevo)
        os.environ["SIBILA_DB_PATH"] = str(nuevo / "sibila.db")
        cfg = config.load_config()
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        db.init_db(cfg.db_path)
        fallos, _, lineas = doc_mod.doctor(cfg)
        self.assertEqual(fallos, 0, [m for e, m in lineas if e == "FALLO"])
        self.assertIn("12 tablas", str(lineas))

    def test_lid176_hash_malo_es_fallo(self):  # rev. Dijkstra M1
        # lid.176.ftz tiene hash fijado (tools/descargar_recursos.SHA256_LID176):
        # presente con sha-256 que NO coincide → FALLO, como los NRC.
        self._parchea_deps()
        self._init_db()
        rec = self.cfg.data_dir / "recursos"
        rec.mkdir(parents=True, exist_ok=True)
        (rec / "lid.176.ftz").write_bytes(b"modelo trucado")
        fallos, _, lineas = doc_mod.doctor(self.cfg)
        self.assertTrue(any("lid.176" in m for e, m in lineas
                            if e == "FALLO"), lineas)

    def test_lid176_sin_tools_es_fallo_de_verificabilidad(self):  # rev. T2R2-1
        # Falla-CERRADA: si tools/ no es importable (layout roto), un
        # lid.176.ftz presente NO sale con el OK genérico "sin hash fijado"
        # — es un FALLO de verificabilidad (Hamilton lo reprodujo con
        # __import__ parcheado; aquí se anula el helper, misma frontera).
        from unittest import mock
        self._parchea_deps()
        self._init_db()
        rec = self.cfg.data_dir / "recursos"
        rec.mkdir(parents=True, exist_ok=True)
        (rec / "lid.176.ftz").write_bytes(b"modelo")
        with mock.patch.object(doc_mod, "_sha256_lid176", lambda: None):
            fallos, _, lineas = doc_mod.doctor(self.cfg)
        self.assertTrue(any("lid.176" in m for e, m in lineas
                            if e == "FALLO"), lineas)
        self.assertFalse(any("lid.176" in m for e, m in lineas
                             if e == "OK"), lineas)

    def test_lid176_hash_bueno_no_es_fallo(self):  # rev. Dijkstra M1 (positivo)
        import hashlib
        import tools.descargar_recursos as dr
        from unittest import mock
        self._parchea_deps()
        self._init_db()
        rec = self.cfg.data_dir / "recursos"
        rec.mkdir(parents=True, exist_ok=True)
        contenido = b"modelo fasttext de verdad"
        (rec / "lid.176.ftz").write_bytes(contenido)
        with mock.patch.object(dr, "SHA256_LID176",
                               hashlib.sha256(contenido).hexdigest()):
            fallos, _, lineas = doc_mod.doctor(self.cfg)
        self.assertFalse(any("lid.176" in m for e, m in lineas
                             if e == "FALLO"), lineas)

    def test_dict_sha_vacio_es_fallo(self):
        # SHA256_ESPERADOS vacío → FALLO "hashes no fijados" (D3); cuando el
        # dict ya esté fijado (T2 §1), este test verifica que NO hay FALLO.
        self._init_db()
        import sibila.procesado.emocion as emo
        fallos, _, lineas = doc_mod.doctor(self.cfg)
        hay_fallo_hashes = any("hashes no fijados" in m
                               for e, m in lineas if e == "FALLO")
        self.assertEqual(hay_fallo_hashes, not emo.SHA256_ESPERADOS)

    def test_centinela_sin_lingua(self):
        self._parchea_deps()   # registra _dep_real para restaurar en tearDown
        doc_mod._dep = lambda nombre: nombre != "lingua"  # lingua ausente
        self._init_db()
        rec = self.cfg.data_dir / "recursos"
        rec.mkdir(parents=True)
        (rec / "SIN_LINGUA").write_text("skip explicito", encoding="ascii")
        _, _, lineas = doc_mod.doctor(self.cfg)
        self.assertTrue(any("skip explícito" in m for e, m in lineas))

    def test_git_ots_nunca_fallo(self):
        self._parchea_deps()
        self._init_db()
        _, _, lineas = doc_mod.doctor(self.cfg)
        for estado, msg in lineas:
            if "git" in msg or "ots" in msg:
                self.assertNotEqual(estado, "FALLO", msg)

    def test_data_dir_no_escribible_es_fallo(self):
        self._init_db()
        self.cfg.data_dir.chmod(0o555)
        try:
            fallos, _, lineas = doc_mod.doctor(self.cfg)
            self.assertTrue(any("no escribible" in m
                                for e, m in lineas if e == "FALLO"))
        finally:
            self.cfg.data_dir.chmod(0o755)


class TestDoctorCli(unittest.TestCase):
    def test_exit_1_sin_db_y_resumen_roto(self):
        with tempfile.TemporaryDirectory() as td:
            r = _cli_doctor(Path(td))
            self.assertEqual(r.returncode, 1)
            self.assertIn("doctor: ROTO", r.stdout)

    def test_exit_0_con_db(self):
        with tempfile.TemporaryDirectory() as td:
            env = _cfg(Path(td))
            env["PYTHONPATH"] = os.pathsep.join([str(DEPS), str(REPO)])
            subprocess.run([sys.executable, "-m", "sibila", "init"],
                           capture_output=True, text=True, env=env, cwd=td)
            r = _cli_doctor(Path(td))
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("doctor: SANO", r.stdout)
            self.assertIn("12 tablas", r.stdout)

    def test_sin_config_local_aviso_d6(self):
        with tempfile.TemporaryDirectory() as td:
            r = _cli_doctor(Path(td))
            self.assertIn("hmac_key", r.stdout)   # AVISO D6


if __name__ == "__main__":
    unittest.main()

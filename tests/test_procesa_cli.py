"""T1 · comando `sibila procesa` (plan Liskov §10.17, C-B4-7).
Exit codes congelados 0/1/2; marcadores [OK]/[AVISO]/[FALLO]/[INFO]."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import io
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from sibila import cli, db
from sibila.procesado.bot_heur import BOT_VERSION


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sibila José Pérez ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "sibila.db"
        db.init_db(self.db_path)
        self._env = mock.patch.dict(os.environ,
                                    {"SIBILA_DB_PATH": str(self.db_path),
                                     "SIBILA_DATA_DIR": str(self.root / "datos")})
        self._env.start()
        self.addCleanup(self._env.stop)

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:  # argparse: uso incorrecto
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def _doc(self, body="texto de prueba con contenido suficiente", dia="2026-08-20"):
        self._n = getattr(self, "_n", 0) + 1
        con = db.connect(self.db_path)
        try:
            with db.tx(con):
                con.execute(
                    "INSERT OR IGNORE INTO sources(nombre, peso) VALUES ('f1', 1.0)")
                con.execute(
                    "INSERT INTO documents(source_id, url_hash, published_at,"
                    " published_at_real, fetched_at, body_text, content_hash, dia)"
                    " VALUES (1, ?, ?, 1, ?, ?, ?, ?)",
                    (f"u{self._n}", f"{dia}T10:00:00Z", f"{dia}T11:00:00Z",
                     body, f"h{self._n}", dia))
        finally:
            con.close()


class TestProcesaCli(Base):
    def test_cero_pendientes_ok(self):  # C-B4-7: 0 trabajo es [OK], no aviso
        code, out, _ = self._run("procesa")
        self.assertEqual(code, 0)
        self.assertIn("[OK] procesa: sin documentos pendientes", out)

    def test_lote_invalido_exit_2(self):
        code, _, err = self._run("procesa", "--lote", "0")
        self.assertEqual(code, 2)
        self.assertIn("--lote", err)

    def test_limite_invalido_exit_2(self):
        code, _, err = self._run("procesa", "--limite", "0")
        self.assertEqual(code, 2)

    def test_dia_invalido_exit_2(self):
        code, _, err = self._run("procesa", "--dia", "20-08-2026")
        self.assertEqual(code, 2)
        self.assertIn("--dia", err)

    def test_bd_inexistente_exit_1(self):
        self.db_path.unlink()
        code, _, err = self._run("procesa")
        self.assertEqual(code, 1)
        self.assertIn("ejecuta 'sibila init'", err)

    def test_procesa_y_resumen_con_contadores(self):  # regex estilo C-B2-10
        for _ in range(3):
            self._doc()
        code, out, _ = self._run("procesa")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"\[INFO\] procesa: 3 procesados, \d+ excluidos "
                              r"\(fecha/dup/idioma\), \d+ near-dup, \d+ republicados, "
                              r"\d+ errores, \d+ días recalculados")
        # sin detector en sandbox → degradado con [AVISO]
        self.assertIn("[AVISO]", out)
        con = db.connect(self.db_path)
        self.addCleanup(con.close)
        n = con.execute(
            "SELECT COUNT(*) FROM documents WHERE calidad_score IS NOT NULL").fetchone()[0]
        self.assertEqual(n, 3)
        versiones = {r[0] for r in con.execute(
            "SELECT bot_detector_version FROM documents")}
        self.assertEqual(versiones, {BOT_VERSION})

    def test_limite_deja_pendientes(self):
        for _ in range(3):
            self._doc()
        code, out, _ = self._run("procesa", "--limite", "2")
        self.assertEqual(code, 0)
        code, out, _ = self._run("procesa")
        self.assertIn("1 procesados", out)

    def test_dia_restringe_seleccion(self):
        self._doc(dia="2026-08-20")
        self._doc(dia="2026-08-21")
        code, out, _ = self._run("procesa", "--dia", "2026-08-21")
        self.assertEqual(code, 0)
        self.assertIn("1 procesados", out)
        con = db.connect(self.db_path)
        self.addCleanup(con.close)
        nulo = con.execute("SELECT COUNT(*) FROM documents"
                           " WHERE dia = '2026-08-20' AND calidad_score IS NULL"
                           ).fetchone()[0]
        self.assertEqual(nulo, 1)

    def test_todo_reprocesa(self):
        self._doc()
        self._run("procesa")
        code, out, _ = self._run("procesa", "--todo")
        self.assertEqual(code, 0)
        self.assertIn("1 procesados", out)

    def test_fallo_de_lote_exit_1(self):
        self._doc()
        with mock.patch("sibila.procesa.procesar_lote",
                        side_effect=__import__("sqlite3").OperationalError("boom")):
            code, _, err = self._run("procesa")
        self.assertEqual(code, 1)
        self.assertRegex(err, r"\[FALLO\] lote a partir de id \d+: boom")


if __name__ == "__main__":
    unittest.main()

"""T1 · comando `sibila detecta` (plan Liskov Bloque 5 §5, C-B5-7).
Exit codes congelados 0/1/2/130; validaciones ANTES de abrir la BD (trampa 12).
La capa pura se inyecta vía dobles (el agente de Turing entrega la fachada)."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from sibila import cli, db, detecta
from tests.test_detecta import MotorFake, SeriesFake, eval_item

HOY = date(2026, 8, 24)
AYER = "2026-08-23"


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
        self.motor = MotorFake()
        self.series = SeriesFake()
        # La capa pura real aún no expone la fachada §3: inyectamos los dobles
        self._capa = mock.patch.object(detecta, "_capa",
                                       lambda m, s: (self.motor, self.series))
        self._capa.start()
        self.addCleanup(self._capa.stop)
        self._reloj = mock.patch.object(detecta.db, "now_iso",
                                        lambda: f"{HOY.isoformat()}T06:00:00Z")
        self._reloj.start()
        self.addCleanup(self._reloj.stop)

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def _siembra(self, dias=30, hasta=AYER):
        con = db.connect(self.db_path)
        self.addCleanup(con.close)
        fin = date.fromisoformat(hasta)
        with db.tx(con):
            con.execute("INSERT INTO sources(nombre, peso) VALUES ('f1', 1.0)")
            cur = con.execute("INSERT INTO terms(text, type) VALUES ('crisis', 'term')")
            tid = cur.lastrowid
        for i in range(dias):
            d = (fin - timedelta(days=dias - 1 - i)).isoformat()
            with db.tx(con):
                for j in range(6):
                    con.execute(
                        "INSERT INTO documents(source_id, url_hash, published_at,"
                        " published_at_real, fetched_at, body_text, content_hash,"
                        " calidad_score, dia) VALUES (1, ?, ?, 1, ?, 'c', ?, 0.5, ?)",
                        (f"u{d}{j}", f"{d}T10:00:00Z", f"{d}T11:00:00Z", f"h{d}{j}", d))
                con.execute(
                    "INSERT INTO term_stats(day, term_id, docs, occ, df)"
                    " VALUES (?, ?, 6, 6, 6)", (d, tid))
        return con


class TestDetectaCli(Base):
    def test_defecto_evalua_ayer_utc(self):
        self._siembra()
        code, out, _ = self._run("detecta")
        self.assertEqual(code, 0)
        self.assertIn(f"{AYER}: 0 alertas", out)   # ayer UTC (reloj inyectado)
        self.assertIn("[OK] detecta: ejecución terminada", out)

    def test_uso_incorrecto_exit_2(self):
        self._siembra(dias=3)
        for argv in (("detecta", "--dia", "2026-08-23", "--desde", "2026-08-01"),
                     ("detecta", "--hasta", "2026-08-23"),
                     ("detecta", "--desde", "2026-08-23", "--hasta", "2026-08-01"),
                     ("detecta", "--dia", "23/08/2026"),
                     ("detecta", "--dia", "2026-8-3"),  # strptime la aceptaba (M1)
                     ("detecta", "--todo", "--desde", "2026-08-01")):
            code, _, err = self._run(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("[FALLO]", err)

    def test_bd_inexistente_exit_1(self):
        self.db_path.unlink()
        code, _, err = self._run("detecta")
        self.assertEqual(code, 1)
        self.assertIn("ejecuta 'sibila init'", err)

    def test_sin_datos_primer_dia(self):
        code, out, _ = self._run("detecta")
        self.assertEqual(code, 0)
        self.assertIn("[OK] detecta: sin datos suficientes (primer día)", out)

    def test_resumen_con_contadores_y_alertas(self):
        con = self._siembra()
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("4.5"), s_cusum=Decimal("6.0"), p_mk=Decimal("0.01"),
            alerta=True)
        code, out, _ = self._run("detecta", "--dia", AYER)
        self.assertEqual(code, 0)
        self.assertRegex(out, rf"\[INFO\] {AYER}: 1 alertas \(0 inmaduras\), "
                              rf"1 elegibles, 0 ítems ciegos")
        self.assertRegex(out, r"\[INFO\] detecta: 1 días evaluados, 3 señales "
                              r"nuevas/actualizadas \(0 inmaduras\)")
        n = con.execute("SELECT COUNT(*) FROM signals WHERE day = ?",
                        (AYER,)).fetchone()[0]
        self.assertEqual(n, 3)

    def test_aviso_dia_hueco(self):
        self._siembra(dias=30, hasta="2026-08-22")
        code, out, _ = self._run("detecta", "--dia", AYER)
        self.assertEqual(code, 0)
        self.assertIn("[AVISO]", out)
        self.assertIn("hueco", out)

    def test_todo_desde_el_primer_dia(self):
        self._siembra(dias=4, hasta=AYER)
        code, out, _ = self._run("detecta", "--todo")
        self.assertEqual(code, 0)
        self.assertIn("[INFO] detecta: evaluando 4 días", out)

    def test_ayuda_en_espanol(self):
        code, out, _ = self._run("detecta", "--help")
        self.assertEqual(code, 0)
        self.assertIn("solo ese día", out)
        self.assertIn("primer día del rango", out)

    def test_fallo_detecta_exit_1(self):
        self._siembra()
        with mock.patch.object(detecta, "detectar_dia",
                               side_effect=detecta.DetectaError("boom")):
            code, _, err = self._run("detecta", "--dia", AYER)
        self.assertEqual(code, 1)
        self.assertIn("[FALLO]", err)


if __name__ == "__main__":
    unittest.main()

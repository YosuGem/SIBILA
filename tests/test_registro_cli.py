"""T1 · comando `sibila registro {sellar,verificar,anclar,listar}` (plan §7).
Exit codes congelados 0/1/2/130; verificar exactamente 0/1 (§4.4)."""
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
from datetime import datetime
from pathlib import Path
from unittest import mock

from sibila import cli, db, sella
from tests.test_sella import HOY, AYER, capa_fake


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
        self.capa = capa_fake()
        # doble inyectado mientras el agente de Turing entrega la fachada real
        self._p = mock.patch.object(sella, "_capa", lambda c=None: self.capa)
        self._p.start()
        self.addCleanup(self._p.stop)
        self._reloj = mock.patch.object(sella.db, "now_iso",
                                        lambda: HOY.strftime("%Y-%m-%dT%H:%M:%SZ"))
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

    def _senal(self, dia=AYER, tema="crisis", status="confirmado"):
        con = db.connect(self.db_path)
        try:
            with db.tx(con):
                con.execute("INSERT OR IGNORE INTO terms(text, type) VALUES (?, 'term')",
                            (tema,))
                tid = con.execute("SELECT id FROM terms WHERE text = ?",
                                  (tema,)).fetchone()[0]
                con.execute(
                    "INSERT INTO signals(day, target_type, target_id, metric, score,"
                    " status, created_at) VALUES (?, 'term', ?, 'z_r', 4.5, ?, ?)",
                    (dia, tid, status, f"{dia}T00:00:00Z"))
        finally:
            con.close()

    def _fichero(self):
        return self.root / "datos" / "registro" / "predicciones.jsonl"


class TestRegistroSellarCli(Base):
    def test_sin_senales_ok(self):
        code, out, _ = self._run("registro", "sellar")
        self.assertEqual(code, 0)
        self.assertIn("[OK] registro: sin señales que sellar", out)

    def test_sellar_ok_con_resumen(self):
        self._senal()
        code, out, _ = self._run("registro", "sellar", "--dia", AYER)
        self.assertEqual(code, 0)
        self.assertRegex(out, r"\[OK\] registro: 1 predicciones selladas "
                              r"\(1 inmaduras\), 0 omitidas \(ya pendientes\), "
                              r"0 reconciliadas")

    def test_uso_incorrecto_exit_2(self):
        for argv in (("registro", "sellar", "--hasta", AYER),
                     ("registro", "sellar", "--dia", AYER, "--desde", "2026-08-01"),
                     ("registro", "sellar", "--desde", "2026-08-23",
                      "--hasta", "2026-08-01"),
                     ("registro", "sellar", "--dia", "23/08/2026")):
            code, _, err = self._run(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("[FALLO]", err)

    def test_bd_inexistente_exit_1(self):
        self.db_path.unlink()
        code, _, err = self._run("registro", "sellar")
        self.assertEqual(code, 1)
        self.assertIn("ejecuta 'sibila init'", err)

    def test_cola_coja_exit_1_mensaje_exacto(self):
        self._senal()
        self._run("registro", "sellar", "--dia", AYER)
        ruta = self._fichero()
        ruta.write_bytes(ruta.read_bytes()[:-10])
        self._senal(tema="otra")
        code, _, err = self._run("registro", "sellar", "--dia", AYER)
        self.assertEqual(code, 1)
        self.assertIn("última línea incompleta (crash previo)", err)
        self.assertIn("intervención manual requerida", err)


class TestRegistroVerificarCli(Base):
    def test_verificar_integro_exit_0(self):
        self._senal()
        self._run("registro", "sellar", "--dia", AYER)
        code, out, _ = self._run("registro", "verificar")
        self.assertEqual(code, 0)
        self.assertIn("[OK] registro: ÍNTEGRO", out)
        self.assertRegex(out, r"\[INFO\] registro: 1 líneas, último hash [0-9a-f]{8},")

    def test_verificar_roto_exit_1(self):
        self._senal()
        self._run("registro", "sellar", "--dia", AYER)
        ruta = self._fichero()
        lineas = ruta.read_bytes().split(b"\n")
        lineas[0] = lineas[0].replace(b"crisis", b"Crisis")  # manipulación
        ruta.write_bytes(b"\n".join(lineas))
        code, _, err = self._run("registro", "verificar")
        self.assertEqual(code, 1)
        self.assertIn("registro: ROTO", err if "ROTO" in err else _)

    def test_verificar_exactamente_0_o_1(self):  # contrato §4.4
        self._senal()
        self._run("registro", "sellar", "--dia", AYER)
        code, _, _ = self._run("registro", "verificar")
        self.assertIn(code, (0, 1))
        ruta = self._fichero()
        ruta.write_bytes(ruta.read_bytes().replace(b"\n", b"\r\n"))
        code, _, _ = self._run("registro", "verificar")
        self.assertEqual(code, 1)


class TestRegistroListarCli(Base):
    def test_listar_lee_la_tabla(self):
        self._senal()
        self._run("registro", "sellar", "--dia", AYER)
        code, out, _ = self._run("registro", "listar")
        self.assertEqual(code, 0)
        self.assertIn("crisis", out)
        self.assertIn("pendiente", out)
        # la tabla, no el fichero: borro el fichero y listar sigue funcionando
        self._fichero().unlink()
        code, out, _ = self._run("registro", "listar", "--pendientes")
        self.assertEqual(code, 0)
        self.assertIn("crisis", out)

    def test_listar_vacio(self):
        code, out, _ = self._run("registro", "listar")
        self.assertEqual(code, 0)
        self.assertIn("sin predicciones", out)


class TestRegistroAnclarCli(Base):
    def test_anclaje_error_es_fallo_accionable(self):  # rev. Dijkstra M3
        # AnclajeError (SibilaError) → [FALLO] con la causa, NUNCA el handler
        # genérico "error inesperado".
        from sibila import anclaje
        self._senal()
        self._run("registro", "sellar", "--dia", AYER)
        with mock.patch.object(anclaje, "anclar",
                               side_effect=anclaje.AnclajeError("git roto")):
            code, _, err = self._run("registro", "anclar")
        self.assertEqual(code, 1)
        self.assertIn("git roto", err)
        self.assertNotIn("error inesperado", err)

    def test_sin_git_aviso_y_exit_0(self):
        self._senal()
        self._run("registro", "sellar", "--dia", AYER)
        with mock.patch("shutil.which", return_value=None):
            code, out, _ = self._run("registro", "anclar")
        self.assertEqual(code, 0)
        self.assertIn("git no encontrado: anclaje pendiente", out)
        con = db.connect(self.db_path)
        self.addCleanup(con.close)
        v = con.execute("SELECT valor FROM ops_metrics WHERE clave = "
                        "'registro.anclajes'").fetchone()[0]
        self.assertEqual(v, 0.0)

    def test_ayuda_en_espanol(self):
        code, out, _ = self._run("registro", "--help")
        self.assertEqual(code, 0)
        self.assertIn("sellar", out)
        self.assertIn("verificar", out)


if __name__ == "__main__":
    unittest.main()

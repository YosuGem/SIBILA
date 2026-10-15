"""T1 · CLI `informe` y `alerta {enviar,probar,digest}` (plan §7, C-B7-8).
Exit codes congelados 0/1/2/130. La capa pura y la red son dobles inyectados
(el humo extremo a extremo vive en test_informe/test_alerta)."""
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
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from sibila import alerta, cli, db, informe_datos
from tests.test_alerta import capa_fake
from tests.test_informe import capa_informe_fake

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
        # dobles de las capas puras y de la red (inyectables por diseño)
        self._p1 = mock.patch.object(informe_datos, "_capa",
                                     lambda c=None: capa_informe_fake())
        self._p2 = mock.patch.object(alerta, "_capa", lambda c=None: capa_fake())
        self._p3 = mock.patch.object(alerta, "enviar_red",
                                     lambda cfg, canal, msg: None)
        self._p4 = mock.patch.object(alerta, "_canales_habilitados",
                                     lambda cfg: (["telegram"], []))
        for p in (self._p1, self._p2, self._p3, self._p4):
            p.start()
            self.addCleanup(p.stop)

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def _senal(self, dia=AYER, tema="crisis", z_r=4.5, status="confirmado"):
        con = db.connect(self.db_path)
        try:
            with db.tx(con):
                con.execute("INSERT OR IGNORE INTO terms(text, type) VALUES (?, 'term')",
                            (tema,))
                tid = con.execute("SELECT id FROM terms WHERE text = ?",
                                  (tema,)).fetchone()[0]
                con.execute(
                    "INSERT INTO signals(day, target_type, target_id, metric, score,"
                    " status, created_at) VALUES (?, 'term', ?, 'z_r', ?, ?, ?)",
                    (dia, tid, z_r, status, f"{dia}T00:00:00Z"))
        finally:
            con.close()


class TestInformeCli(Base):
    def test_informe_stdout_exit_0(self):
        code, out, _ = self._run("informe", "--dia", AYER)
        self.assertEqual(code, 0)
        self.assertIn("# SIBILA — informe", out)
        self.assertIn("[OK] informe:", out)

    def test_informe_semana_defecto_es_la_de_ayer(self):
        code, out, _ = self._run("informe")
        self.assertEqual(code, 0)
        self.assertIn("..", out)             # rango semanal, no un solo día

    def test_informe_a_fichero_con_meta(self):
        ruta = self.root / "salida.md"
        code, out, _ = self._run("informe", "--dia", AYER, "--salida", str(ruta))
        self.assertEqual(code, 0)
        self.assertTrue(ruta.exists())
        self.assertTrue((self.root / "salida.md.meta.json").exists())
        self.assertIn(f"en {ruta}", out)

    def test_salida_extension_ambigua_exit_2(self):
        code, _, err = self._run("informe", "--dia", AYER,
                                 "--salida", str(self.root / "x.txt"))
        self.assertEqual(code, 2)
        self.assertIn("--formato", err)

    def test_uso_incorrecto_exit_2(self):
        for argv in (("informe", "--semana", "2026-08-17"),
                     ("informe", "--semana", "2026-W99"),
                     ("informe", "--hasta", AYER),
                     ("informe", "--dia", "ayer")):
            code, _, err = self._run(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("[FALLO]", err)

    def test_bd_inexistente_exit_1(self):
        self.db_path.unlink()
        code, _, err = self._run("informe")
        self.assertEqual(code, 1)
        self.assertIn("ejecuta 'sibila init'", err)

    def test_formato_invalido_se_valida_antes_de_la_bd(self):  # rev. Dijkstra M8
        # Flags ANTES de abrir la BD: --formato inválido con BD ausente →
        # exit 2 (error de uso), no exit 1 de "no existe la BD".
        self.db_path.unlink()
        code, _, err = self._run("informe", "--formato", "xml")
        self.assertEqual(code, 2)
        self.assertIn("no soportado", err)
        self.assertIn("md, json, csv", err)

    def test_actualizar_gdelt_es_subaccion_aparte(self):
        with mock.patch("sibila.gdelt.actualizar") as act:
            act.return_value = {"escritos": 1, "vacios": 0, "fallos": 0,
                                "avisos": []}
            with mock.patch("sibila.gdelt.temas_de_la_semana",
                            return_value=["crisis"]):
                code, out, _ = self._run("informe", "--actualizar-gdelt")
        self.assertEqual(code, 0)
        self.assertIn("[OK] gdelt:", out)


class TestAlertaCli(Base):
    def test_enviar_sin_alertas_ok(self):
        code, out, _ = self._run("alerta", "enviar", "--dia", AYER)
        self.assertEqual(code, 0)
        self.assertIn("[OK] alerta: sin alertas que enviar", out)

    def test_enviar_con_alerta_ok_y_lineas(self):
        self._senal()
        code, out, _ = self._run("alerta", "enviar", "--dia", AYER)
        self.assertEqual(code, 0)
        self.assertIn("[OK] telegram: crisis nivel alerta", out)
        self.assertIn("[INFO] alerta: 1 enviadas, 0 cooldown, 0 fallos", out)

    def test_enviar_todos_los_canales_caen_exit_1(self):
        self._senal()
        with mock.patch.object(alerta, "enviar_red",
                               side_effect=ConnectionError("caído")):
            code, _, err = self._run("alerta", "enviar", "--dia", AYER)
        self.assertEqual(code, 1)
        self.assertIn("todos los canales", err)
        # el fallo quedó registrado como 'fallo:telegram' (B1)
        con = db.connect(self.db_path)
        self.addCleanup(con.close)
        self.assertEqual(con.execute("SELECT canal FROM alert_log").fetchone()[0],
                         "fallo:telegram")

    def test_enviar_uso_incorrecto_exit_2(self):
        code, _, err = self._run("alerta", "enviar", "--hasta", AYER)
        self.assertEqual(code, 2)

    def test_probar_ok(self):
        code, out, _ = self._run("alerta", "probar")
        self.assertEqual(code, 0)
        self.assertIn("[OK] alerta: mensaje de prueba recibido por telegram", out)

    def test_probar_sin_credenciales_exit_1(self):
        with mock.patch.object(alerta, "_canales_habilitados",
                               lambda cfg: ([], ["telegram: sin credenciales"])):
            code, _, err = self._run("alerta", "probar")
        self.assertEqual(code, 1)
        self.assertIn("sin credenciales", err)

    def test_digest_ok_y_anti_dup(self):
        code, out, _ = self._run("alerta", "digest")
        self.assertEqual(code, 0)
        self.assertIn("digest", out)
        code2, out2, _ = self._run("alerta", "digest")
        self.assertEqual(code2, 0)
        self.assertIn("no enviado", out2)    # misma semana: anti-duplicación

    def test_sin_credenciales_pero_todo_suprimido_exit_0(self):  # rev. Dijkstra M2
        # Sin credenciales Y nada que enviar (cooldown lo suprimió todo):
        # NO es fallo — exit 0 (solo falla si había algo pendiente de enviar).
        self._senal()
        ahora_txt = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        con = db.connect(self.db_path)
        try:
            with db.tx(con):   # alerta reciente del tema → cooldown suprime
                sid = con.execute("SELECT MAX(id) FROM signals").fetchone()[0]
                con.execute(
                    "INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                    " VALUES (?, 'alerta', 'telegram', ?)", (sid, ahora_txt))
        finally:
            con.close()
        with mock.patch.object(alerta, "_canales_habilitados",
                               lambda cfg: ([], ["telegram: sin credenciales"])):
            code, out, _ = self._run("alerta", "enviar", "--dia", AYER)
        self.assertEqual(code, 0)
        self.assertIn("cooldown", out)

    def test_ayuda_en_espanol(self):
        code, out, _ = self._run("alerta", "--help")
        self.assertEqual(code, 0)
        self.assertIn("enviar", out)
        self.assertIn("digest", out)


if __name__ == "__main__":
    unittest.main()

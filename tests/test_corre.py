"""T1 · `sibila corre` (CLI + orquestador): orden de etapas, stop en etapa,
validaciones exit 2, conexión fresca por etapa, guardián AST de reloj (C-T1).
El humo E2E con vectores vive en test_t1_e2e.py."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import ast
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sibila import cli, corre, db

DIA = "2026-06-01"

FEED = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<rss version=\"2.0\">\n"
        "  <channel>\n    <title>t1</title>\n"
        "    <item>\n      <title>x</title>\n"
        "      <link>https://t1.invalid/2026-06-01/0</link>\n"
        "      <guid>https://t1.invalid/2026-06-01/0</guid>\n"
        "      <pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate>\n"
        "      <description>cuerpo de prueba del fixture corre</description>\n"
        "    </item>\n  </channel>\n</rss>\n")


class TestCorreModulo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        self.db_path = self.tmp / "t.db"
        db.init_db(self.db_path)
        self.cfg = SimpleNamespace(data_dir=self.tmp / "datos",
                                   db_path=self.db_path, secretos={})
        self.ahora = datetime(2026, 6, 2, 6, 0, tzinfo=timezone.utc)

    def test_orden_de_etapas_no_conmutable(self):
        orden = []
        for mod, fn in (("procesa", "ejecutar"), ("detecta", "ejecutar"),
                        ("sella", "ejecutar"), ("alerta", "ejecutar")):
            m = __import__(f"sibila.{mod}", fromlist=[fn])
            self._mk(m, fn, orden, mod)
        corre.ejecutar_dia(self.cfg, dia=DIA, ahora=self.ahora)
        self.assertEqual(orden, ["procesa", "detecta", "sella", "alerta"])

    def _mk(self, m, fn, orden, nombre):
        def falsa(*a, **k):
            orden.append(nombre)
            return {"avisos": [], "contadores": {}, "pendientes": 0,
                    "sin_alertas": True}
        setattr(self, f"_p{nombre}", mock.patch.object(m, fn, falsa))
        getattr(self, f"_p{nombre}").start()
        self.addCleanup(getattr(self, f"_p{nombre}").stop)

    def test_stop_en_la_etapa_que_falla(self):
        import sibila.detecta as det
        import sibila.sella as sel
        llamadas = []
        with mock.patch.object(det, "ejecutar",
                               side_effect=det.DetectaError("boom")):
            with mock.patch.object(sel, "ejecutar",
                                   lambda *a, **k: llamadas.append("sellar")):
                with self.assertRaises(corre.CorreError) as cm:
                    corre.ejecutar_dia(self.cfg, dia=DIA, ahora=self.ahora)
        self.assertEqual(cm.exception.etapa, "detecta")
        self.assertEqual(llamadas, [])          # ni sellar ni alerta

    def test_ahora_naive_rechazado(self):
        with self.assertRaises(corre.CorreError):
            corre.ejecutar_dia(self.cfg, dia=DIA,
                               ahora=datetime(2026, 6, 2, 6, 0))

    def test_dia_sin_fixture_es_hueco_real(self):
        r = corre.ejecutar_dia(self.cfg, dia=DIA, ahora=self.ahora,
                               fixtures=None)
        self.assertEqual(r["ingesta_nuevos"], 0)
        self.assertNotIn("ingesta:t1", r["etapas"])   # sin ingesta, sin error

    def test_linea_resumen_compacta(self):
        r = corre.ejecutar_dia(self.cfg, dia=DIA, ahora=self.ahora)
        linea = corre.linea_resumen(r)
        self.assertRegex(linea, r"^\[OK\] corre 2026-06-01: ingesta 0 nuevos · "
                                r"procesa 0 · detecta 0 alertas · registro 0 "
                                r"selladas · alerta 0 enviadas$")

    def test_guardian_ast_sin_reloj_en_corre(self):
        """corre.py JAMÁS llama datetime.now()/date.today() (C-T1; el default
        vive solo en cli._ahora_defecto_cli)."""
        # Ruta anclada al fichero de test, nunca al cwd (defecto mecánico
        # hallado en la revisión de puntos ciegos 2026-10-13: desde otro cwd
        # el guardián no encontraba el fuente y fallaba en falso).
        fuente = (Path(__file__).resolve().parent.parent
                  / "sibila" / "corre.py")
        arbol = ast.parse(fuente.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Attribute) and nodo.attr in ("now", "today"):
                self.fail(f"reloj real en corre.py: {nodo.attr}")


class TestCorreCli(unittest.TestCase):
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
        con = db.connect(self.db_path)
        with db.tx(con):
            con.execute("INSERT INTO sources(nombre, tipo, idioma, peso)"
                        " VALUES ('t1', 'web', 'es', 1.0)")
        con.close()
        self.feed = self.root / "feed.xml"
        self.feed.write_bytes(FEED.encode("utf-8"))
        # Recursos simulados (ALTO-1): desde el centinela _AUTO, `corre` carga
        # el modelo y los léxicos reales; el CLI corre in-process, así que se
        # inyectan los mismos dobles que usa la batería de procesa.
        from tests.test_procesa import DetectorFalso, _lex
        self._p_det = mock.patch("sibila.procesado.idioma.cargar_detector",
                                 return_value=DetectorFalso("es"))
        self._p_lex = mock.patch("sibila.procesado.emocion.cargar_lexicos",
                                 return_value=_lex())
        self._p_det.start()
        self._p_lex.start()
        self.addCleanup(self._p_det.stop)
        self.addCleanup(self._p_lex.stop)

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_todos_los_canales_caidos_exit_1(self):  # rev. Hamilton M2
        # Consistencia con `alerta enviar`: si TODOS los canales habilitados
        # caen, el pipeline termina exit 1 (Task Scheduler no reintenta).
        falso = {"dia": DIA, "avisos": [], "ingesta_nuevos": 0,
                 "etapas": {"alerta": {"todos_caidos": True,
                                       "contadores": {"enviadas": 0,
                                                      "fallos": 2}}}}
        with mock.patch.object(corre, "ejecutar_dia", return_value=falso):
            code, _, err = self._run("corre", "--dia", DIA)
        self.assertEqual(code, 1)
        self.assertIn("todos los canales", err)

    def test_hand_off_procesa_recibe_hoy_del_dia(self):  # rev. Hamilton N4 · D-047
        # corre inyecta hoy=dia a procesa: el ts de ops_metrics del paso es el
        # DÍA ANALÍTICO (23:59:59Z), no el reloj del anfitrión. Sin el hoy=d
        # (la mutación), procesa estampa con db.now_iso() real.
        code, _, err = self._run("corre", "--dia", DIA, "--fuente", "t1",
                                 "--fixture", str(self.feed))
        self.assertEqual(code, 0, err)
        con = db.connect(self.db_path)
        try:
            tss = {r[0] for r in con.execute(
                "SELECT ts FROM ops_metrics WHERE clave LIKE 'procesa.%'")}
        finally:
            con.close()
        self.assertEqual(tss, {f"{DIA}T23:59:59Z"})

    def test_corre_con_fixture_exit_0_linea_compacta(self):
        code, out, err = self._run("corre", "--dia", DIA, "--fuente", "t1",
                                   "--fixture", str(self.feed))
        self.assertEqual(code, 0, err)
        self.assertIn(f"[OK] corre {DIA}: ingesta 1 nuevos", out)
        # 12 tablas exactamente, ninguna nueva (C-T1-8)
        con = db.connect(self.db_path)
        self.addCleanup(con.close)
        tablas = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(len(tablas), 12)

    def test_trabajo_sin_recursos_es_rojo_no_verde(self):  # ALTO-1
        # Anti falso-éxito: hay documentos que procesar y los recursos de
        # idioma NO cargaron → el día no puede terminar en verde.
        self._p_det.stop()
        self._p_lex.stop()
        code, out, err = self._run("corre", "--dia", DIA, "--fuente", "t1",
                                   "--fixture", str(self.feed))
        self.assertEqual(code, 1)
        self.assertIn("procesamiento analítico no realizado", err)
        self.assertNotIn("[OK] corre", out)

    def test_rango_con_fixture_usa_recursos_no_degradado(self):  # ALTO-1, rev. cruce
        # ejecutar_rango hereda el centinela _AUTO: un rango con fixture y
        # recursos (dobles inyectados) es verde y poblado, no ROJO ni degradado.
        d2 = "2026-06-02"
        feed2 = self.root / "feed2.xml"
        feed2.write_bytes(FEED.replace("2026-06-01", d2)
                          .replace("01 Jun 2026", "02 Jun 2026")
                          .replace("cuerpo de prueba del fixture corre",
                                   "segundo cuerpo distinto del fixture corre")
                          .encode("utf-8"))
        rango_dir = self.root / "rango"
        rango_dir.mkdir()
        (rango_dir / f"{DIA}.xml").write_bytes(self.feed.read_bytes())
        (rango_dir / f"{d2}.xml").write_bytes(feed2.read_bytes())
        code, out, err = self._run("corre", "--desde", DIA, "--hasta", d2,
                                   "--fuente", "t1",
                                   "--fixture-dir", str(rango_dir))
        self.assertEqual(code, 0, err)
        con = db.connect(self.db_path)
        try:
            nulos = con.execute("SELECT SUM(lang IS NULL) FROM documents").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(nulos, 0)

    def test_dia_malo_tras_historico_bueno_es_rojo(self):  # ALTO-1, rev. cruce
        # El control es por día: un histórico sano NO tapa un día degradado.
        code, _, err = self._run("corre", "--dia", DIA, "--fuente", "t1",
                                 "--fixture", str(self.feed))
        self.assertEqual(code, 0, err)          # día 1 con recursos (dobles)
        self._p_det.stop()                       # día 2: los recursos "caen"
        self._p_lex.stop()
        d2 = "2026-06-02"
        feed2 = self.root / "feed2.xml"
        feed2.write_bytes(FEED.replace("2026-06-01", d2)
                          .replace("01 Jun 2026", "02 Jun 2026")
                          .replace("cuerpo de prueba del fixture corre",
                                   "segundo cuerpo distinto del fixture corre")
                          .encode("utf-8"))
        code, out, err = self._run("corre", "--dia", d2, "--fuente", "t1",
                                   "--fixture", str(feed2))
        self.assertEqual(code, 1)                # ROJO pese al histórico bueno
        self.assertIn("procesamiento analítico no realizado", err)

    def test_reintento_tras_rojo_sigue_rojo_hasta_remediar(self):  # ALTO-1, rev. cruce
        # Tras un día ROJO, reejecutar sin más NO pone el día verde: los docs
        # quedaron lang NULL. El mensaje indica la remediación (procesa --todo).
        self._p_det.stop()
        self._p_lex.stop()
        code, _, _ = self._run("corre", "--dia", DIA, "--fuente", "t1",
                               "--fixture", str(self.feed))
        self.assertEqual(code, 1)
        self._p_det.start()                      # "recursos restaurados"
        self._p_lex.start()
        code, _, err = self._run("corre", "--dia", DIA, "--fuente", "t1",
                                 "--fixture", str(self.feed))
        self.assertEqual(code, 1)                # sigue ROJO sin re-procesar
        self.assertIn("procesa --todo", err)
        # Remediación real: re-procesado completo y repetición del día
        code, _, err = self._run("procesa", "--todo")
        self.assertEqual(code, 0, err)
        code, out, err = self._run("corre", "--dia", DIA, "--fuente", "t1",
                                   "--fixture", str(self.feed))
        self.assertEqual(code, 0, err)           # ahora sí, verde con analítica
        self.assertIn("[OK] corre", out)


    def test_dia_hueco_sin_recursos_sigue_verde(self):  # ALTO-1 (legítimo)
        # Sin documentos nuevos ni pendientes no hay analítica que exigir:
        # el hueco real es éxito aunque falten los recursos.
        self._p_det.stop()
        self._p_lex.stop()
        code, out, err = self._run("corre", "--dia", DIA)
        self.assertEqual(code, 0, err)
        self.assertIn(f"[OK] corre {DIA}: ingesta 0 nuevos", out)

    def test_uso_incorrecto_exit_2(self):
        for argv in (("corre", "--fixture", str(self.feed)),          # sin --dia/--fuente
                     ("corre", "--dia", DIA, "--fixture", str(self.feed)),  # sin --fuente
                     ("corre", "--fixture-dir", str(self.root)),       # sin --desde
                     ("corre", "--dia", "ayer"),
                     ("corre", "--hasta", DIA)):
            code, _, err = self._run(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("[FALLO]", err)

    def test_bd_inexistente_exit_1(self):
        self.db_path.unlink()
        code, _, err = self._run("corre", "--dia", DIA)
        self.assertEqual(code, 1)
        self.assertIn("ejecuta 'sibila init'", err)

    def test_sin_flags_analiza_ayer(self):         # C-T1-2: producción intacta
        code, out, _ = self._run("corre")
        self.assertEqual(code, 0)
        from datetime import datetime, timedelta, timezone
        # MED-1 resuelta (D-077): el día por defecto es AYER UTC, nunca local
        ayer = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        self.assertIn(f"[OK] corre {ayer}:", out)

    def test_flags_digest_y_con_informe(self):
        code, out, err = self._run("corre", "--dia", DIA, "--fuente", "t1",
                                   "--fixture", str(self.feed),
                                   "--digest", "--con-informe")
        self.assertEqual(code, 0, err)
        self.assertIn("[OK] corre", out)
        self.assertIn("== Resumen ==", out)       # informe md por stdout


if __name__ == "__main__":
    unittest.main()

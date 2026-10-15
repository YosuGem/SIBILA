"""T1 (D-047): asserts SQL A1-A10 sobre el estado FINAL del humo de superficie
(mismo patrón de cadena que tests/test_e2e_t1_humo.py; BD propia en tmp).

A1 usa el predicado REAL de procesa.pendientes (calidad_score /
bot_detector_version), no un proxy. Idempotencia por COUNT total + clave
lógica (A7). A8: 'fallo:digest' presente, canal='digest' = 0 sin credenciales,
exit de `alerta enviar` = 1 si hay señales pendientes, 0 si no las hay (el
humo de superficie no produce señales: exige 57 días de serie; la ruta
exit-1 la cubren los tests de la capa de datos de alertas).
"""
import inspect
import sqlite3
import unittest

from tests.test_e2e_t1_humo import FIXTURE, FUENTES, HumoBase


class TestEstadoFinal(HumoBase, unittest.TestCase):
    """Una sola pasada de la cadena + segunda pasada para idempotencia."""

    @classmethod
    def setUpClass(cls):
        cls.preparar()
        for cmd in (["init"],
                    ["ingesta", "--fuentes", str(FUENTES), "--fuente",
                     "lobsters", "--fixture", str(FIXTURE)],
                    ["procesa"], ["detecta"], ["registro", "sellar"],
                    ["registro", "verificar"], ["alerta", "digest"],
                    ["alerta", "enviar"]):
            r = cls().cli(*cmd)
            assert r.returncode == 0, (cmd, r.stdout, r.stderr)
        cls.enviar = cls().cli("alerta", "enviar")   # exit code inspeccionado

    @classmethod
    def tearDownClass(cls):
        cls.limpiar()

    def setUp(self):
        self.con = sqlite3.connect(self.data / "sibila.db")

    def tearDown(self):
        self.con.close()

    def _n(self, sql, *args):
        return self.con.execute(sql, args).fetchone()[0]

    # A1 — predicado REAL de procesa.pendientes
    def test_a1_pendientes_cero(self):
        from sibila.procesado.bot_heur import BOT_VERSION
        pend = self._n("SELECT COUNT(*) FROM documents WHERE calidad_score"
                       " IS NULL OR bot_detector_version IS NULL"
                       " OR bot_detector_version != ?", BOT_VERSION)
        self.assertEqual(pend, 0)
        self.assertGreater(self._n("SELECT COUNT(*) FROM documents"), 0)

    # A2 — stats del día ↔ documentos del día
    def test_a2_stats_coherentes_con_documentos(self):
        huerfanas = self._n("SELECT COUNT(*) FROM term_stats WHERE day NOT IN"
                            " (SELECT DISTINCT dia FROM documents)")
        self.assertEqual(huerfanas, 0)
        # En el humo sin detector de idioma (sin lid.176.ftz) los docs quedan
        # excluidos por idioma: 0 filas es lo esperable; si hay stats, deben
        # ser de días con documentos (asertado arriba).

    # A3 — dominio de signals
    def test_a3_signals_dominio(self):
        mal = self._n("SELECT COUNT(*) FROM signals WHERE metric NOT IN"
                      " ('z_r','cusum','mk') OR score IS NULL")
        self.assertEqual(mal, 0)

    # A4 — predictions: solo z_r, dominio de estado, dedup por clave lógica
    def test_a4_predictions_dominio(self):
        mal = self._n("SELECT COUNT(*) FROM predictions WHERE metrica != 'z_r'"
                      " OR estado NOT IN ('pendiente','acertada','fallada',"
                      "'expirada')")
        self.assertEqual(mal, 0)

    # A5 — enviar sin credenciales no inserta nada accionable
    def test_a5_enviar_no_inserta(self):
        mal = self._n("SELECT COUNT(*) FROM alert_log WHERE signal_id IS NULL"
                      " AND canal != 'fallo:digest'")
        self.assertEqual(mal, 0)

    # A6 — ops_metrics tras la cadena
    def test_a6_ops_metrics(self):
        claves = {r[0] for r in
                  self.con.execute("SELECT clave FROM ops_metrics")}
        self.assertTrue(any(c.startswith("ingesta.") and c.endswith(".lobsters") for c in claves))
        self.assertTrue(any(c.startswith("procesa.") for c in claves))
        self.assertTrue(any(c.startswith("registro.") for c in claves))
        # detecta.* solo se escribe cuando hay datos evaluables (el humo es
        # primer día → "sin datos suficientes" no escribe): aserción blanda
        # documentada, la dura está en test_detecta.

    # A7 — idempotencia por COUNT total + clave lógica
    def test_a7_idempotencia_reprocesar_dia(self):
        antes = {t: self._n(f"SELECT COUNT(*) FROM {t}")
                 for t in ("documents", "term_stats", "signals",
                           "predictions")}
        # alert_log EXCLUIDO: crece con cada digest fallido (diseño); la
        # idempotencia fina de alert_log es TODO I6 (fix del otro coder).
        # TODO(I6): incluir alert_log cuando aterrice el fix de procesa/alerta.
        r_ing = None
        for cmd in (["ingesta", "--fuentes", str(FUENTES), "--fuente",
                     "lobsters", "--fixture", str(FIXTURE)],
                    ["procesa"], ["detecta"], ["registro", "sellar"]):
            r = self.cli(*cmd)
            self.assertEqual(r.returncode, 0, r.stderr)
            if cmd[0] == "ingesta":
                r_ing = r
        for t, n in antes.items():
            self.assertEqual(self._n(f"SELECT COUNT(*) FROM {t}"), n,
                             f"idempotencia rota en {t}")
        # clave lógica: la re-ingesta del fixture cuenta como duplicados url
        self.assertIn("0 nuevos", r_ing.stdout)

    # A8 — digest sin credenciales: fallo registrado, cero envíos, exit code
    def test_a8_digest_fallo_y_enviar_exit(self):
        self.assertGreaterEqual(
            self._n("SELECT COUNT(*) FROM alert_log WHERE canal='fallo:digest'"),
            1)
        self.assertEqual(
            self._n("SELECT COUNT(*) FROM alert_log WHERE canal='digest'"), 0)
        pend = self._n("SELECT COUNT(*) FROM signals WHERE status IN"
                       " ('confirmado','inmaduro')")
        esperado = 1 if pend else 0
        self.assertEqual(self.enviar.returncode, esperado,
                         self.enviar.stdout + self.enviar.stderr)

    # A9 — verificación del registro: exit 0 tras la cadena
    def test_a9_verificar_ok(self):
        r = self.cli("registro", "verificar")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ÍNTEGRO", r.stdout)

    # A10 — ninguna pendiente marcada 'expirada' erróneamente
    # (GDELT/resolución real es T2: TODO(T2) vector de vencimiento)
    def test_a10_pendientes_no_expiradas(self):
        mal = self._n("SELECT COUNT(*) FROM predictions WHERE estado='expirada'")
        self.assertEqual(mal, 0)   # en el humo no hay resolución GDELT (T2)


class TestProcesaSinHoyRegresion(unittest.TestCase):
    """C-T1-7: procesa SIN el parámetro `hoy` se comporta byte-idéntico.
    El parámetro lo añade el otro coder (I5); este test pasa ANTES (firma sin
    hoy: aserto trivial) y DESPUÉS (default None y re-ejecución idéntica)."""

    def test_firma_y_reejecucion(self):
        from sibila import procesa
        sig = inspect.signature(procesa.ejecutar)
        if "hoy" in sig.parameters:          # fix I5 ya aterrizado
            self.assertIsNone(sig.parameters["hoy"].default)
        # Re-ejecución sin `hoy` sobre la BD del humo: resultado idéntico
        # (byte-igual en las columnas derivadas de documents)
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory(prefix="sibila José Pérez T1 ") as td:
            import os
            from tests.test_e2e_t1_humo import _entorno, _sibila
            data = Path(td) / "datos"
            for cmd in (["init"],
                        ["ingesta", "--fuentes", str(FUENTES), "--fuente",
                         "lobsters", "--fixture", str(FIXTURE)], ["procesa"]):
                r = _sibila(cmd, data, Path(td))
                assert r.returncode == 0, (cmd, r.stderr)
            con = sqlite3.connect(data / "sibila.db")
            cols = ("id, dia, calidad_score, bot_flags, bot_detector_version,"
                    " simhash, lang, peso")
            antes = con.execute(f"SELECT {cols} FROM documents"
                                " ORDER BY id").fetchall()
            r = _sibila(["procesa"], data, Path(td))   # segunda pasada sin hoy
            assert r.returncode == 0, r.stderr
            despues = con.execute(f"SELECT {cols} FROM documents"
                                  " ORDER BY id").fetchall()
            con.close()
            self.assertEqual(antes, despues)


if __name__ == "__main__":
    unittest.main()

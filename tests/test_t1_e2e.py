"""T1 · E2E multi-día en proceso (plan_t1_turing §4, D-047).

TP-N3-E2E (verdad j/k exacta), TP-N8-E2E (idempotencia pipeline post-fix
CC-T1-1), cooldowns 72/24 h inter-día (§4.3, CC-T1-2), digest 168 h (§4.4),
vencimiento sin resolvedor (§4.5), crash/recuperación (§4.6), generador
determinista (T-T1-12). Sin red real: `enviar` fake; vectores congelados
reproducidos, no cambiados.
"""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sibila import alerta, corre, db, informe_datos, sella
from tests.helpers import sintetico_e2e as gen
from tests.helpers.arnes import (FUENTE, ahora_del_dia, correr_escenario,
                                 preparar_bd)

UTC = timezone.utc
D31, D32 = "2026-07-01", "2026-07-02"


def _utc(txt):
    return datetime.strptime(txt, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


class Escenario32(unittest.TestCase):
    """setUpClass: los 32 días congelados con dobles (una sola corrida)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        cls.cfg = preparar_bd(cls.tmp)
        cls.envios = correr_escenario(cls.cfg, cls.tmp)
        cls.con = db.connect(cls.cfg.db_path)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _q(self, sql, *p):
        return self.con.execute(sql, p).fetchall()


class TestVerdadConocida(Escenario32):  # TP-N3-E2E · vectores (j)(k) §3.2/§3.3
    def test_escenario_576_docs_sin_dup_ni_error(self):
        self.assertEqual(self._q("SELECT COUNT(*) FROM documents")[0][0], 576)
        self.assertEqual(self._q(
            "SELECT COUNT(*) FROM documents WHERE duplicate_of IS NOT NULL")[0][0], 0)
        self.assertEqual(self._q(
            "SELECT COUNT(*) FROM documents WHERE calidad_score IS NULL")[0][0], 0)

    def test_vector_j_zr_cusum_mk_exactos(self):
        esperado = {  # día → (z_r, S_cusum, p_mk) congelados §3.2
            "2026-06-29": (4.0470, 3.5469, 0.0627),
            "2026-06-30": (3.3725, 6.4194, 0.0319),
            "2026-07-01": (4.0470, 9.9663, 0.0243)}
        for dia, _vals in esperado.items():
            z = self._q("SELECT ts.z_r FROM term_stats ts JOIN terms t"
                        " ON t.id = ts.term_id WHERE t.text = 'terremoto'"
                        " AND ts.day = ?", dia)[0][0]
            self.assertAlmostEqual(z, esperado[dia][0], places=4)
        mets = {(r[0], r[1]): round(r[2], 4) for r in self._q(
            "SELECT s.day, s.metric, s.score FROM signals s JOIN terms t"
            " ON t.id = s.target_id WHERE t.text = 'terremoto'")}
        for dia, (z, cus, mk) in esperado.items():
            if dia == D31:
                self.assertEqual(mets[(dia, "z_r")], round(z, 4))
                self.assertEqual(mets[(dia, "cusum")], round(cus, 4))
                self.assertEqual(mets[(dia, "mk")], round(mk, 4))
            else:  # días 29-30: z_r en term_stats pero SIN signals (§3.2)
                self.assertNotIn((dia, "z_r"), mets)

    def test_vector_j_dia31_seis_signals_y_dos_predicciones(self):
        filas = self._q(
            "SELECT s.target_type, t.text, s.metric, s.status FROM signals s"
            " JOIN terms t ON t.id = s.target_id WHERE s.day = ?", D31)
        self.assertEqual(len(filas), 6)          # 3 term + 3 cluster
        self.assertEqual({r[3] for r in filas}, {"confirmado"})
        self.assertEqual({r[0] for r in filas}, {"term", "cluster"})
        preds = self._q("SELECT tema, metrica, umbral, ventana, madura"
                        " FROM predictions WHERE created_at LIKE '2026-07-02%'")
        self.assertEqual(len(preds), 2)
        for tema, metrica, umbral, ventana, madura in preds:
            self.assertEqual((metrica, umbral, ventana, madura),
                             ("z_r", "3.0000", "P7D", 1))

    def test_vector_k_emocion_exacta(self):
        n = self._q("SELECT COUNT(*), MIN(n), MIN(n_efectivo) FROM emo_stats"
                    " WHERE lang = 'es'")[0]
        self.assertEqual((n[0], n[1]), (32, 11))
        self.assertGreaterEqual(n[2], 10.0)      # gate emoción (assert temprano)
        self.assertLess(abs(11.0 - n[2]), 0.001)  # ≈10,999x congelado (ver nota)
        vals = {r[0]: round(r[1], 4) for r in self._q(
            "SELECT day, valence_mean FROM emo_stats ORDER BY day")}
        for i, dia in enumerate(sorted(vals)):
            self.assertEqual(vals[dia], gen.VALENCIAS[i])
        sig = {r[0]: round(r[1], 4) for r in self._q(
            "SELECT s.metric, s.score FROM signals s JOIN terms t"
            " ON t.id = s.target_id WHERE s.target_type = 'emocion'"
            " AND s.day = ?", D32)}
        self.assertEqual(sig, {"z_r": 6.0705, "cusum": 22.2817, "mk": 0.0102})
        self.assertEqual(self._q(
            "SELECT COUNT(*) FROM signals WHERE target_type = 'emocion'"
            " AND day < ?", D32)[0][0], 0)       # días 29-31 sin alerta (MK)

    def test_registro_3_lineas_cadena_ok(self):
        self.assertEqual(self._q("SELECT COUNT(*) FROM predictions")[0][0], 3)
        ruta = self.cfg.data_dir / "registro" / "predicciones.jsonl"
        self.assertEqual(len(ruta.read_bytes().splitlines()), 3)
        res = sella.verificar(self.cfg, self.con)
        self.assertTrue(res["ok"], res.get("roturas"))
        hashes = [r[0] for r in self._q("SELECT hash FROM predictions")]
        self.assertEqual(len(set(hashes)), 3)
        self.assertEqual(self._q("SELECT COUNT(*) FROM predictions"
                                 " WHERE madura = 1")[0][0], 3)

    def test_informe_w27_con_metricas_del_periodo(self):
        con_ro = informe_datos.conectar_ro(self.cfg.db_path)
        try:
            r = informe_datos.ejecutar(self.cfg, con_ro, desde="2026-06-29",
                                       hasta="2026-07-05",
                                       ahora=_utc("2026-07-06T06:00:00Z"))
        finally:
            con_ro.close()
        c = r["contenido"]
        self.assertIn("terremoto", c)
        self.assertIn("emocion (es)", c)          # mapeo D-T7-7
        self.assertIn("n/d", c)                   # GDELT sin red
        self.assertRegex(c, r"items elegibles: [1-9]")   # NO cero por ts real
        self.assertGreaterEqual(len([l for l in c.splitlines()
                                     if l.startswith("== ")]), 7)  # 7 secciones


class TestTPN8E2E(Escenario32):  # §4.2 · idempotencia pipeline (post CC-T1-1)
    def _proyeccion(self, tabla):
        excl = {"signals": "id, created_at", "alert_log": "rowid, sent_at",
                "ops_metrics": "rowid, ts"}.get(tabla)
        cols = [r[1] for r in self._q(f"PRAGMA table_info({tabla})")
                if not excl or r[1] not in excl.split(", ")]
        return sorted(repr(tuple(r)) for r in
                      self._q(f"SELECT {', '.join(cols)} FROM {tabla}"))

    def test_recorrer_dia31_tras_alertar_es_idempotente(self):
        ids_antes = sorted(r[0] for r in self._q("SELECT id FROM signals"))
        proy = {t: self._proyeccion(t) for t in
                ("documents", "terms", "term_stats", "emo_stats", "signals",
                 "predictions", "alert_log")}
        ruta = self.cfg.data_dir / "registro" / "predicciones.jsonl"
        jsonl_antes = ruta.read_bytes()
        n_envios = len(self.envios)
        # Re-corre el día 31 con el MISMO fixture y el MISMO ahora (§4.2)
        res = corre.ejecutar_dia(
            self.cfg, dia=D31, ahora=ahora_del_dia(30),
            fixtures={FUENTE: self.tmp / "feeds" / f"{D31}.xml"},
            detector=__import__("tests.test_procesa", fromlist=["DetectorFalso"]).DetectorFalso("es"),
            lexicos=__import__("tests.test_procesa", fromlist=["_lex"])._lex(),
            enviar=lambda c, ch, m: self.envios.append((None, ch, m)))
        self.assertEqual(res["etapas"]["ingesta:t1"]["nuevos"], 0)
        self.assertEqual(res["etapas"]["procesa"]["pendientes"], 0)
        self.assertEqual(res["etapas"]["sellar"]["contadores"]["selladas"], 0)
        self.assertEqual(res["etapas"]["sellar"]["contadores"]["omitidas"], 2)
        self.assertEqual(res["etapas"]["alerta"]["contadores"]["enviadas"], 0)
        self.assertEqual(
            res["etapas"]["alerta"]["contadores"]["cooldown_omitidas"], 2)
        self.assertEqual(ruta.read_bytes(), jsonl_antes)   # JSONL byte-idéntico
        for t, antes in proy.items():
            self.assertEqual(self._proyeccion(t), antes, t)
        self.assertEqual(sorted(r[0] for r in self._q("SELECT id FROM signals")),
                         ids_antes)                # signals.id CONSERVADOS (FK)
        self.assertEqual(len(self.envios), n_envios)   # alert_log sin filas nuevas


class TestCooldowns(Escenario32):  # §4.3 · 72 h alerta / 24 h alarma (CC-T1-2)
    def _enviar(self, desde, hasta, ahora_txt):
        envios = []
        res = alerta.ejecutar(self.cfg, self.con, desde=desde, hasta=hasta,
                              ahora=_utc(ahora_txt),
                              enviar=lambda c, ch, m: envios.append(m))
        return res, envios

    def test_secuencia_cooldown_bordes_exactos(self):
        # Envíos iniciales del pico (del setUpClass): term+cluster alerta día 31
        # a las 2026-07-02T06:00Z; emocion alarma día 32 a las 2026-07-03T06:00Z.
        msgs = [m for _, _, m in self.envios]
        self.assertTrue(any(m.startswith("sibila alerta: terremoto") for m in msgs))
        self.assertTrue(any(m.startswith("sibila alerta: cluster:") for m in msgs))
        alarma = [m for m in msgs if m.startswith("sibila alarma")]
        self.assertEqual(len(alarma), 1)
        self.assertIn("emocion:es", alarma[0])
        filas = self._q("SELECT l.nivel, l.sent_at, t.text FROM alert_log l"
                        " JOIN signals s ON s.id = l.signal_id"
                        " JOIN terms t ON t.id = s.target_id ORDER BY l.sent_at")
        por_tema = {}
        for nivel, sent, tema in filas:
            por_tema.setdefault(tema, []).append((nivel, sent))
        self.assertEqual(por_tema["terremoto"], [("alerta", "2026-07-02T06:00:00Z")])
        self.assertEqual(por_tema["emocion:es"], [("alarma", "2026-07-03T06:00:00Z")])
        self.assertFalse(any(r[0].startswith("fallo:") for r in
                             self._q("SELECT canal FROM alert_log")))
        # 1 · reintento 2026-07-04T05:59:59Z: tema 47:59:59 <72 h, emoción
        # 23:59:59 <24 h → las tres suprimidas
        res, envios = self._enviar(D31, D32, "2026-07-04T05:59:59Z")
        self.assertEqual(envios, [])
        self.assertEqual(res["contadores"]["cooldown_omitidas"], 3)
        # 2 · borde alarma ==24 h exactas: permitida (comparación estricta)
        res, envios = self._enviar(D32, D32, "2026-07-04T06:00:00Z")
        self.assertEqual(len(envios), 1)
        self.assertIn("emocion:es", envios[0])
        # 3 · borde alerta ==72 h exactas CON LA RED CAÍDA: el intento se
        # registra como fallo:telegram y NO enfría (B1)
        res2 = alerta.ejecutar(self.cfg, self.con, desde=D31, hasta=D31,
                               ahora=_utc("2026-07-05T06:00:00Z"),
                               enviar=lambda c, ch, m: (_ for _ in ()).throw(
                                   ConnectionError("red caída")))
        self.assertEqual(res2["contadores"]["fallos"], 2)
        # 4 · reintento inmediato (2 s después): permitido (fallo no enfría
        # y el borde ==72 h ya era permitido)
        res3, envios3 = self._enviar(D31, D31, "2026-07-05T06:00:02Z")
        self.assertEqual(len(envios3), 2)


class TestDigest(Escenario32):  # §4.4 · digest semanal / ventana 168 h
    def _digest(self, desde, hasta, ahora_txt):
        envios = []
        res = alerta.digest(self.cfg, self.con, desde=desde, hasta=hasta,
                            ahora=_utc(ahora_txt),
                            enviar=lambda c, ch, m: envios.append(m))
        return res, envios

    def test_secuencia_digest_168h(self):
        # Día 7 (2026-06-08T06:00Z): semana 1 sin alertas → "(sin alertas...)"
        res, envios = self._digest("2026-06-01", "2026-06-07", "2026-06-08T06:00:00Z")
        self.assertTrue(res["enviado"])
        self.assertIn("(sin alertas en la semana)", envios[0])
        self.assertEqual(self._q("SELECT COUNT(*) FROM alert_log"
                                 " WHERE canal = 'digest'")[0][0], 1)
        # Reintento 24 h después: omitido, SIN fila nueva
        res, _ = self._digest("2026-06-01", "2026-06-07", "2026-06-09T06:00:00Z")
        self.assertFalse(res["enviado"])
        self.assertIn("ya enviado", res["motivo"])
        self.assertEqual(self._q("SELECT COUNT(*) FROM alert_log"
                                 " WHERE canal = 'digest'")[0][0], 1)
        # Día 14 a la misma hora: 168 h exactas → permitido
        res, _ = self._digest("2026-06-08", "2026-06-14", "2026-06-15T06:00:00Z")
        self.assertTrue(res["enviado"])
        # Semana del pico (2026-06-29..07-05) el 2026-07-06T06:00Z:
        # 5 líneas = 2 vigilancias (días 29-30) + term + cluster + emoción
        res, envios = self._digest("2026-06-29", "2026-07-05", "2026-07-06T06:00:00Z")
        self.assertTrue(res["enviado"])
        cuerpo = envios[0].splitlines()[1:]
        self.assertEqual(len(cuerpo), 5)
        texto = "\n".join(cuerpo)
        self.assertIn("vigilancia: terremoto (2026-06-29)", texto)
        self.assertIn("vigilancia: terremoto (2026-06-30)", texto)
        self.assertIn("terremoto (2026-07-01)", texto)
        self.assertIn("emocion:es (2026-07-02)", texto)


class TestVencimiento(Escenario32):  # §4.5 · sin resolvedor en Fase 1
    def test_realerta_tras_vencimiento_sella_nueva_linea(self):
        tid = self._q("SELECT id FROM terms WHERE text = 'terremoto'")[0][0]
        # La predicción original de terremoto se creó 2026-07-02 (ventana P7D);
        # una nueva señal el 2026-07-20 (>7 días) la encuentra VENCIDA para la
        # dedup (vencida() de la pura). NO se muta created_at: el cruce
        # byte-exacto fichero↔tabla de verificar seguiría roto (lección §4.4).
        with db.tx(self.con):
            # señal sintética marcada del día posterior controlado
            self.con.execute(
                "INSERT INTO signals(day, target_type, target_id, metric, score,"
                " status, created_at) VALUES ('2026-07-20', 'term', ?, 'z_r',"
                " 5.0, 'confirmado', '2026-07-20T00:00:00Z')", (tid,))
        res = sella.ejecutar(self.cfg, self.con, dia="2026-07-20",
                             ahora=_utc("2026-07-21T06:00:00Z"))
        self.assertEqual(res["contadores"]["selladas"], 1)
        self.assertEqual(self._q("SELECT COUNT(*) FROM predictions")[0][0], 4)
        vieja = self._q("SELECT estado FROM predictions WHERE tema = 'terremoto'"
                        " ORDER BY created_at")[0][0]
        self.assertEqual(vieja, "pendiente")       # sin resolvedor: NO expirada
        self.assertTrue(sella.verificar(self.cfg, self.con)["ok"])


class TestCrashEntreEtapas(unittest.TestCase):  # §4.6.1
    def test_abortar_tras_ingesta_y_reanudar(self):
        tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        cfg = preparar_bd(tmp)
        gen.escribir_escenario(tmp / "feeds")
        from tests.test_procesa import DetectorFalso, _lex
        det, lex = DetectorFalso("es"), _lex()
        # solo ingesta de los 31 primeros días (crash antes de procesa)
        from sibila import ingesta
        for i in range(31):
            d = gen.DIA_1 + timedelta(days=i)
            con = db.connect(cfg.db_path)
            try:
                ingesta.ingestar(cfg, corre._ConectorFixture(
                    FUENTE, tmp / "feeds" / f"{d}.xml"), None, con,
                    hoy=ahora_del_dia(i))
            finally:
                con.close()
        # reanudar el pipeline completo: cada día se procesa una sola vez
        envios = []
        resumenes = []
        for i in range(31):
            d = gen.DIA_1 + timedelta(days=i)
            r = corre.ejecutar_dia(cfg, dia=d.isoformat(), ahora=ahora_del_dia(i),
                                   fixtures=None, detector=det, lexicos=lex,
                                   enviar=lambda c, ch, m: envios.append(m))
            resumenes.append(r)
        con = db.connect(cfg.db_path)
        self.addCleanup(con.close)
        n = con.execute("SELECT COUNT(*) FROM documents WHERE dia = ?", (D31,)
                        ).fetchone()[0]
        self.assertEqual(n, 23)                    # 12 tema + 11 emoción
        self.assertEqual(con.execute("SELECT COUNT(*) FROM signals WHERE day = ?",
                                     (D31,)).fetchone()[0], 6)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 2)
        self.assertTrue(sella.verificar(cfg, con)["ok"])
        self.assertEqual(sum(1 for r in resumenes
                             if r["ingesta_nuevos"] == 0), 31)


class TestGeneradorDeterminista(unittest.TestCase):  # T-T1-12
    def test_mismo_input_mismos_bytes(self):
        from datetime import date
        a = gen.generar_dia(date(2026, 6, 15), 7, 0.4)
        b = gen.generar_dia(date(2026, 6, 15), 7, 0.4)
        self.assertEqual(hashlib.sha256(a).hexdigest(),
                         hashlib.sha256(b).hexdigest())

    def test_conteos_congelados(self):
        self.assertEqual(sum(gen.CONTEOS_TEMA), 224)
        self.assertEqual(sum(gen.CONTEOS_TEMA) + 32 * 11, 576)
        self.assertEqual(len(gen.CONTEOS_TEMA), 32)
        self.assertEqual(len(gen.VALENCIAS), 32)

    def test_valencia_fuera_de_ley_falla_temprano(self):
        from datetime import date
        with self.assertRaises(KeyError):
            gen.generar_dia(date(2026, 6, 1), 5, 0.7)


if __name__ == "__main__":
    unittest.main()

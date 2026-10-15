"""T1 · capa de datos de detecta.py (plan Liskov Bloque 5 §7, trampas 1-14).

La capa pura (sibila/deteccion/) es de Turing y se construye EN PARALELO: aquí
se usan DOBLES conformes al contrato §3/§6 congelado (SerieDiaria, EvalItem sin
status, elegible, evaluar). Cuando la capa real exista, los tests de humo
TP-N3/TP-N8-reales corren con ella (skip si ausente).
"""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sibila import db, detecta

HOY = date(2026, 8, 24)          # reloj congelado: 'ayer' = 2026-08-23
AYER = "2026-08-23"


# ---------- Dobles de la capa pura (contrato §3: Decimal4 HALF_UP al final) ----

@dataclass(frozen=True)
class SerieDiariaFake:
    dias: tuple
    valores: tuple


def eval_item(z_r=None, s_cusum=None, p_mk=None, pendiente=None, racha_z=0,
              cusum_cruza=False, alerta=False):
    """EvalItem sin status (E1: el status es de la capa de datos)."""
    return SimpleNamespace(z_r=z_r, s_cusum=s_cusum, p_mk=p_mk, pendiente=pendiente,
                           racha_z=racha_z, cusum_cruza=cusum_cruza, alerta=alerta)


class MotorFake:
    """evaluar(serie, *, elegible) dirigido por regla sobre el valor del día
    evaluado; respeta D-042: la elegibilidad entra como dato y manda."""

    def __init__(self, regla=None):
        self.regla = regla or (lambda s: eval_item(z_r=Decimal("1.0000")))
        self.series_vistas = []
        self.elegibilidades = []

    def evaluar(self, serie, *, elegible=True):
        self.series_vistas.append(serie)
        self.elegibilidades.append(elegible)
        ev = self.regla(serie)
        if not elegible:
            ev.alerta = False
        return ev


class SeriesFake:
    SerieDiaria = SerieDiariaFake

    def __init__(self, elegible=True):
        self._elegible = elegible

    def elegible(self, docs_por_dia):
        return self._elegible(list(docs_por_dia)) if callable(self._elegible) \
            else self._elegible

    @staticmethod
    def es_dia_parcial(docs_totales_dia, mediana_docs_28d):
        # Espejo del contrato congelado (la fórmula real vive en deteccion/)
        return float(docs_totales_dia) < 0.5 * float(mediana_docs_28d)


# ---------- Base ----------

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        self.db_path = self.tmp / f"test_{self._testMethodName}.db"
        db.init_db(self.db_path)
        self.con = db.connect(self.db_path)
        self.addCleanup(self.con.close)
        self.cfg = SimpleNamespace(data_dir=self.tmp)
        with db.tx(self.con):
            self.con.execute("INSERT INTO sources(nombre, peso) VALUES ('f1', 1.0)")
        self._n = 0
        self.motor = MotorFake()
        self.series = SeriesFake()

    def _ejecutar(self, **kw):
        kw.setdefault("ahora", HOY)
        kw.setdefault("motor", self.motor)
        kw.setdefault("series", self.series)
        return detecta.ejecutar(self.cfg, self.con, **kw)

    def _dia(self, dia, n_docs=6, *, procesado=True):
        """Siembra n_docs documentos del día (corpus + evidencia de procesado)."""
        with db.tx(self.con):
            for _ in range(n_docs):
                self._n += 1
                self.con.execute(
                    "INSERT INTO documents(source_id, url_hash, published_at,"
                    " published_at_real, fetched_at, body_text, content_hash,"
                    " calidad_score, dia) VALUES (1, ?, ?, 1, ?, 'cuerpo', ?, ?, ?)",
                    (f"u{self._n}", f"{dia}T10:00:00Z", f"{dia}T11:00:00Z",
                     f"h{self._n}", 0.5 if procesado else None, dia))

    def _term(self, texto="crisis", serie=None, tipo="term"):
        """Alta del término y sus filas term_stats (day, docs) del dict serie."""
        with db.tx(self.con):
            self.con.execute("INSERT OR IGNORE INTO terms(text, type) VALUES (?, ?)",
                             (texto, tipo))
            tid = self.con.execute("SELECT id FROM terms WHERE text = ?",
                                   (texto,)).fetchone()[0]
            for dia, docs in (serie or {}).items():
                self.con.execute(
                    "INSERT OR IGNORE INTO term_stats(day, term_id, docs, occ, df)"
                    " VALUES (?, ?, ?, ?, ?)", (dia, tid, docs, docs, docs))
        return tid

    def _siembra_historia(self, dias=30, hasta=AYER, n_docs=6, con_term=True):
        """Historia limpia de `dias` días acabada en `hasta` (elegible, madura)."""
        fin = date.fromisoformat(hasta)
        serie = {}
        for i in range(dias):
            d = (fin - timedelta(days=dias - 1 - i)).isoformat()
            self._dia(d, n_docs)
            serie[d] = 6
        return self._term("crisis", serie) if con_term else None

    def _signals(self, dia=None):
        q = "SELECT day, target_type, target_id, metric, score, status FROM signals"
        if dia:
            return self.con.execute(q + " WHERE day = ? ORDER BY 1,2,3,4", (dia,)).fetchall()
        return self.con.execute(q + " ORDER BY 1,2,3,4").fetchall()

    def _metricas(self, clave):
        return [r[0] for r in self.con.execute(
            "SELECT valor FROM ops_metrics WHERE clave = ?", (f"detecta.{clave}",))]


class TestZrUpdateOnly(Base):  # mutación (4) · M7
    def test_escribe_zr_sin_tocar_docs_occ_df(self):
        self._siembra_historia()
        tid = self._term("rampa", {AYER: 9})
        self._ejecutar(dia=AYER)
        r = self.con.execute(
            "SELECT docs, occ, df, z_r FROM term_stats WHERE day = ? AND term_id = ?",
            (AYER, tid)).fetchone()
        self.assertEqual((r["docs"], r["occ"], r["df"]), (9, 9, 9))
        self.assertEqual(r["z_r"], 1.0)                 # fake: Decimal("1.0000")

    def test_zr_se_persiste_como_float_del_decimal(self):  # trampa 10
        self._siembra_historia()
        self.motor.regla = lambda s: eval_item(z_r=Decimal("3.1234"))
        self._ejecutar(dia=AYER)
        zr = self.con.execute("SELECT z_r FROM term_stats WHERE day = ? AND z_r IS NOT NULL",
                              (AYER,)).fetchone()[0]
        self.assertIsInstance(zr, float)
        self.assertEqual(zr, float(Decimal("3.1234")))

    def test_update_a_fila_inexistente_es_error_visible(self):  # trampa 8
        self._siembra_historia()
        self._term("fantasma", {AYER: 3})
        real = self.con.execute
        # Rompe la fila justo antes de la fase BD: el UPDATE debe dar rowcount 0
        original = detecta._persistir_dia

        def rompe(con, d, cont, evs, emos, **kw):
            con.execute("DELETE FROM term_stats WHERE day = ?", (d,))
            return original(con, d, cont, evs, emos, **kw)
        import unittest.mock as mock
        with mock.patch.object(detecta, "_persistir_dia", rompe):
            with self.assertRaises(detecta.DetectaError):
                self._ejecutar(dia=AYER)


class TestDiaCiego(Base):
    def test_ciego_no_escribe_y_cuenta(self):
        self._siembra_historia()
        self.motor.regla = lambda s: eval_item(z_r=None)
        res = self._ejecutar(dia=AYER)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM term_stats WHERE day = ? AND z_r IS NOT NULL",
            (AYER,)).fetchone()[0], 0)
        cont = dict(res["dias"])[AYER]
        self.assertGreater(cont["items_ciego"], 0)   # ítems ciegos, no días (M4b)


class TestIdempotencia(Base):  # mutación (1) · TP-N8
    def test_segunda_ejecucion_identica(self):
        self._siembra_historia()
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("4.5000"), s_cusum=Decimal("6.1000"),
            p_mk=Decimal("0.0100"), racha_z=3, cusum_cruza=True, alerta=True)
        self._ejecutar(dia=AYER)
        sig1 = self._signals()
        zr1 = self.con.execute(
            "SELECT day, term_id, z_r FROM term_stats ORDER BY 1, 2").fetchall()
        self._ejecutar(dia=AYER)
        # TP-N8: signals y z_r idénticos (ops_metrics es log append: excluido)
        self.assertEqual([tuple(r) for r in sig1], [tuple(r) for r in self._signals()])
        self.assertEqual([tuple(r) for r in zr1], [tuple(r) for r in self.con.execute(
            "SELECT day, term_id, z_r FROM term_stats ORDER BY 1, 2")])


class TestDeleteInsertSignals(Base):  # mutaciones (2) y (3)
    def test_senal_no_reproducida_desaparece(self):
        self._siembra_historia()
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("4.0"), s_cusum=Decimal("5.0"), p_mk=Decimal("0.01"),
            alerta=True)
        self._ejecutar(dia=AYER)
        self.assertEqual(len(self._signals(AYER)), 3)
        self.motor.regla = lambda s: eval_item(z_r=Decimal("0.5"))   # ya no alerta
        self._ejecutar(dia=AYER)
        self.assertEqual(self._signals(AYER), [])

    def test_reactivo_sobrevive(self):
        self._siembra_historia()
        tid = self.con.execute("SELECT id FROM terms WHERE text = 'crisis'").fetchone()[0]
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO signals(day, target_type, target_id, metric, score,"
                " status, created_at) VALUES (?, 'term', ?, 'z_r', 9.9, 'reactivo',"
                " '2026-08-24T00:00:00Z')", (AYER, tid))
        self._ejecutar(dia=AYER)
        r = self._signals(AYER)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["status"], "reactivo")


class TestStatus(Base):  # N1/N2 · mutaciones (6) y (12)
    def test_confirmado_con_historia_madura(self):
        self._siembra_historia(dias=30)
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("4.0"), s_cusum=Decimal("5.0"), p_mk=Decimal("0.01"),
            alerta=True)
        res = self._ejecutar(dia=AYER)
        self.assertTrue(all(r["status"] == "confirmado" for r in self._signals(AYER)))
        cont = dict(res["dias"])[AYER]
        self.assertEqual(cont["mes_inmaduro"], 0)
        self.assertEqual(cont["alertas"], cont["alertas_inmaduras"] +
                         sum(1 for r in self._signals(AYER)
                             if r["status"] == "confirmado" and r["metric"] == "z_r"))

    def test_inmaduro_con_historia_con_huecos(self):
        # T5 de Turing: inmaduro solo alcanzable con huecos (arranque limpio no)
        primero = "2026-08-15"   # 8 días de calendario antes de AYER
        for d, n in ((primero, 6), ("2026-08-18", 6), ("2026-08-21", 6), (AYER, 6)):
            self._dia(d, n)
        self._term("crisis", {primero: 6, "2026-08-18": 6, "2026-08-21": 6, AYER: 6})
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("4.0"), s_cusum=Decimal("5.0"), p_mk=Decimal("0.01"),
            alerta=True)
        res = self._ejecutar(dia=AYER)
        estados = {r["status"] for r in self._signals(AYER)}
        self.assertEqual(estados, {"inmaduro"})
        cont = dict(res["dias"])[AYER]
        self.assertEqual(cont["mes_inmaduro"], 1)
        self.assertEqual(cont["alertas"], cont["alertas_inmaduras"])


class TestGatesDia(Base):  # mutaciones (5) y (16) · trampas 13/14
    def test_dia_parcial_no_se_evalua_y_zr_queda_null(self):
        self._siembra_historia(dias=30, hasta="2026-08-22", n_docs=6)
        self._dia(AYER, 2)                        # 2 < 0,5×6 → parcial
        self._term("crisis", {AYER: 2})
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("9.0"), s_cusum=Decimal("9.0"), p_mk=Decimal("0.001"),
            alerta=True)
        res = self._ejecutar(dia=AYER)
        cont = dict(res["dias"])[AYER]
        self.assertEqual(cont["dia_parcial"], 1)
        self.assertEqual(cont["dias_evaluados"], 0)
        self.assertEqual(self._signals(AYER), [])
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM term_stats WHERE day = ? AND z_r IS NOT NULL",
            (AYER,)).fetchone()[0], 0)            # jamás z_r huérfano (trampa 14)
        self.assertTrue(any("parcial" in a for a in res["avisos"]))

    def test_dia_al_51_porciento_si_se_evalua(self):
        self._siembra_historia(dias=30, hasta="2026-08-22", n_docs=6)
        self._dia(AYER, 4)                        # 4 ≥ 0,5×6 → sano
        self._term("crisis", {AYER: 4})
        res = self._ejecutar(dia=AYER)
        self.assertEqual(dict(res["dias"])[AYER]["dias_evaluados"], 1)

    def test_dia_al_50_porciento_exacto_se_evalua(self):  # rev. B2/M1 · T-B5-11
        # Frontera EXACTA: docs == 0,5×mediana (3 == 0,5×6) → NO es parcial
        # (comparación estricta): se evalúa y z_r se escribe. Las mutaciones
        # 0,5→0,6 y `<`→`<=` en la ruta de producción mueren aquí.
        self._siembra_historia(dias=30, hasta="2026-08-22", n_docs=6)
        self._dia(AYER, 3)                        # 3 == 0,5 × mediana(6)
        tid = self._term("crisis", {AYER: 3})
        res = self._ejecutar(dia=AYER)
        cont = dict(res["dias"])[AYER]
        self.assertEqual(cont["dia_parcial"], 0)
        self.assertEqual(cont["dias_evaluados"], 1)
        self.assertIsNotNone(self.con.execute(
            "SELECT z_r FROM term_stats WHERE day = ? AND term_id = ?",
            (AYER, tid)).fetchone()[0])
        # Y un documento MENOS sí es parcial (borde inferior ya vetado)
        self._dia("2026-08-24", 2)                # 2 < 0,5×6 → parcial
        self._term("otro", {"2026-08-24": 2})
        res2 = self._ejecutar(dia="2026-08-24", ahora=date(2026, 8, 25))
        self.assertEqual(dict(res2["dias"])["2026-08-24"]["dia_parcial"], 1)

    def test_dia_parcial_entra_en_baselines_futuras(self):  # mutación (18) · M5
        self._siembra_historia(dias=30, hasta="2026-08-22", n_docs=6)
        self._dia(AYER, 2)                        # parcial el 23
        self._dia("2026-08-24", 6)
        self._term("crisis", {AYER: 2, "2026-08-24": 6})
        self._ejecutar(dia="2026-08-24", ahora=date(2026, 8, 25))
        serie = self.motor.series_vistas[-1]
        pos = serie.dias.index(AYER)
        self.assertEqual(serie.valores[pos], 2.0)  # valor real, SIN exclusión

    def test_dia_hueco(self):
        self._siembra_historia(dias=30, hasta="2026-08-22")
        res = self._ejecutar(dia=AYER)            # 0 documentos
        cont = dict(res["dias"])[AYER]
        self.assertEqual(cont["dia_hueco"], 1)
        self.assertEqual(cont["dias_evaluados"], 0)
        self.assertTrue(any("hueco" in a for a in res["avisos"]))

    def test_dia_sin_procesar(self):              # trampa 13 · mutación (15)
        self._siembra_historia(dias=30, hasta="2026-08-22")
        self._dia(AYER, 6, procesado=False)       # calidad_score NULL
        self._term("crisis", {AYER: 6})
        res = self._ejecutar(dia=AYER)
        cont = dict(res["dias"])[AYER]
        self.assertEqual(cont["dia_sin_procesar"], 1)
        self.assertEqual(cont["dias_evaluados"], 0)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM term_stats WHERE day = ? AND z_r IS NOT NULL",
            (AYER,)).fetchone()[0], 0)
        self.assertTrue(any("sin procesar" in a for a in res["avisos"]))

    def test_primer_dia_del_sistema(self):
        res = self._ejecutar(dia=AYER)            # sin stats en absoluto
        self.assertTrue(res["sin_datos"])
        self.assertEqual(res["dias"], [])


class TestSerieMaterializada(Base):  # mutaciones (8), (17) · trampas 3 y 5
    def test_57_posiciones_t_menos_56_a_t(self):
        self._siembra_historia(dias=30, hasta="2026-08-22")
        self._dia(AYER, 6)
        self._term("crisis", {AYER: 6})
        self._ejecutar(dia=AYER)
        serie = self.motor.series_vistas[-1]
        self.assertEqual(len(serie.dias), 57)
        self.assertEqual(serie.dias[0], "2026-06-28")
        self.assertEqual(serie.dias[-1], AYER)

    def test_materializacion_cero_vs_none(self):  # D-B5-04
        self._siembra_historia(dias=5, hasta="2026-08-22")   # 19-22 ago con corpus
        self._dia(AYER, 6)
        self._term("raro", {AYER: 1})                        # solo aparece hoy
        self._ejecutar(dia=AYER)
        serie = self.motor.series_vistas[-1]
        self.assertIsNone(serie.valores[serie.dias.index("2026-08-10")])  # hueco
        self.assertEqual(serie.valores[serie.dias.index("2026-08-21")], 0.0)  # corpus sin ítem
        self.assertEqual(serie.valores[-1], 1.0)

    def test_anti_look_ahead(self):               # trampa 3
        self._siembra_historia(dias=30, hasta="2026-08-22")
        self._dia(AYER, 6)
        self._term("crisis", {AYER: 6})
        # Día FUTURO con valor gigante: no puede cambiar nada del día evaluado
        self._dia("2026-08-25", 6)
        tid = self._term("futuro", {"2026-08-25": 999})
        res = self._ejecutar(dia=AYER)
        for serie in self.motor.series_vistas:
            self.assertLessEqual(serie.dias[-1], AYER)
            self.assertNotIn("2026-08-25", serie.dias)
        self.assertEqual(self.con.execute(
            "SELECT z_r FROM term_stats WHERE day = '2026-08-25' AND term_id = ?",
            (tid,)).fetchone()[0], None)


class TestFronteraMadurez(Base):  # rev. Hamilton M3
    def test_historia_27_inmaduro_y_28_confirmado(self):
        # El día del primer veredicto maduro es un hito: historia == 28 días
        # de calendario → 'confirmado'; 27 → 'inmaduro'. La mutación 28→27
        # muere aquí.
        for dias, esperado in ((28, "inmaduro"), (29, "confirmado")):
            with self.subTest(dias=dias):
                # BD nueva por escenario
                tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez mad "))
                ruta = tmp / "m.db"
                db.init_db(ruta)
                con = db.connect(ruta)
                try:
                    with db.tx(con):
                        con.execute(
                            "INSERT INTO sources(nombre, peso) VALUES ('f1', 1.0)")
                    fin = date.fromisoformat(AYER)
                    for i in range(dias):
                        d = (fin - timedelta(days=dias - 1 - i)).isoformat()
                        with db.tx(con):
                            con.execute(
                                "INSERT INTO documents(source_id, url_hash,"
                                " published_at, published_at_real, fetched_at,"
                                " body_text, content_hash, calidad_score, dia)"
                                " VALUES (1, ?, ?, 1, ?, 'c', ?, 0.5, ?)",
                                (f"u{d}", f"{d}T10:00:00Z", f"{d}T11:00:00Z",
                                 f"h{d}", d))
                            con.execute(
                                "INSERT INTO terms(text, type) VALUES (?, 'term')"
                                " ON CONFLICT(text) DO NOTHING", ("crisis",))
                        tid = con.execute("SELECT id FROM terms WHERE text='crisis'"
                                          ).fetchone()[0]
                        with db.tx(con):
                            con.execute(
                                "INSERT INTO term_stats(day, term_id, docs, occ, df)"
                                " VALUES (?, ?, 6, 6, 6)", (d, tid))
                    motor = MotorFake(lambda s: eval_item(
                        z_r=Decimal("4.0"), s_cusum=Decimal("5.0"),
                        p_mk=Decimal("0.01"), alerta=True))
                    detecta.ejecutar(self.cfg, con, dia=AYER, ahora=HOY,
                                     motor=motor, series=SeriesFake())
                    estados = {r[0] for r in con.execute(
                        "SELECT DISTINCT status FROM signals WHERE day = ?", (AYER,))}
                    self.assertEqual(estados, {esperado})
                finally:
                    con.close()


class TestElegibilidad(Base):
    def test_no_elegible_no_alerta(self):
        self._siembra_historia()
        self.series._elegible = False
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("9.0"), s_cusum=Decimal("9.0"), p_mk=Decimal("0.001"),
            alerta=True)
        res = self._ejecutar(dia=AYER)
        cont = dict(res["dias"])[AYER]
        self.assertEqual(cont["elegibles"], 0)
        self.assertEqual(cont["alertas"], 0)
        self.assertEqual(self._signals(AYER), [])

    def test_elegible_recibe_los_28_dias_previos(self):  # N8
        self._siembra_historia()
        vistos = []
        self.series._elegible = lambda vals: vistos.append(vals) or True
        self._ejecutar(dia=AYER)
        self.assertTrue(vistos)
        self.assertEqual(len(vistos[0]), 28)      # t−28…t−1, nunca el propio día


class TestEmocion(Base):  # mutación (13)
    def _siembra_emo(self, n_ef=12.0, dias=30):
        fin = date.fromisoformat(AYER)
        for i in range(dias):
            d = (fin - timedelta(days=dias - 1 - i)).isoformat()
            self._dia(d, 6)
            with db.tx(self.con):
                self.con.execute(
                    "INSERT INTO emo_stats(day, lang, valence_mean, arousal_mean,"
                    " n, n_efectivo) VALUES (?, 'es', 0.1, 0.2, 6, ?)", (d, n_ef))

    def test_emocion_alerta_con_n_efectivo_suficiente(self):
        self._siembra_emo()
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("4.0"), s_cusum=Decimal("5.0"), p_mk=Decimal("0.01"),
            alerta=True)
        self._ejecutar(dia=AYER)
        filas = [r for r in self._signals(AYER) if r["target_type"] == "emocion"]
        self.assertEqual(len(filas), 3)
        tid = self.con.execute(
            "SELECT id FROM terms WHERE text = 'emocion:es' AND type = 'emocion'"
        ).fetchone()[0]
        self.assertTrue(all(r["target_id"] == tid for r in filas))

    def test_emocion_vetada_con_n_efectivo_bajo(self):
        self._siembra_emo(n_ef=9.9)
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("9.0"), s_cusum=Decimal("9.0"), p_mk=Decimal("0.001"),
            alerta=True)
        self._ejecutar(dia=AYER)
        self.assertEqual([r for r in self._signals(AYER)
                          if r["target_type"] == "emocion"], [])
        # el alta de emocion:es tampoco se produce
        self.assertIsNone(self.con.execute(
            "SELECT 1 FROM terms WHERE text = 'emocion:es'").fetchone())

    def test_frontera_n_efectivo_10_exacto_evalua(self):  # rev. Hamilton M2
        # n_efectivo == 10,0 (MIN_N_EFECTIVO_EMO exacto) → el carril SÍ entra;
        # la mutación 10→11 muere aquí.
        self._siembra_emo(n_ef=10.0)
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("4.0"), s_cusum=Decimal("5.0"), p_mk=Decimal("0.01"),
            alerta=True)
        res = self._ejecutar(dia=AYER)
        filas = [r for r in self._signals(AYER) if r["target_type"] == "emocion"]
        self.assertEqual(len(filas), 3)
        # y por debajo de la frontera (10−ε) queda vetada
        with db.tx(self.con):
            self.con.execute("UPDATE emo_stats SET n_efectivo = 9.9999")
            self.con.execute("DELETE FROM signals")
        res2 = self._ejecutar(dia=AYER)
        self.assertEqual([r for r in self._signals(AYER)
                          if r["target_type"] == "emocion"], [])

    def test_dia_sin_medicion_emocion_es_none_no_cero(self):  # rev. Dijkstra M2
        # Día con corpus pero SIN fila emo_stats (modo degradado): la serie de
        # valence materializa None (no medido), JAMÁS 0,0 (contaminaría las
        # baselines del carril).
        fin = date.fromisoformat(AYER)
        degradado = (fin - timedelta(days=10)).isoformat()
        for i in range(30):
            d = (fin - timedelta(days=29 - i)).isoformat()
            self._dia(d, 6)
            if d == degradado:
                continue                          # día degradado: sin medición
            with db.tx(self.con):
                self.con.execute(
                    "INSERT INTO emo_stats(day, lang, valence_mean, arousal_mean,"
                    " n, n_efectivo) VALUES (?, 'es', 0.1, 0.2, 6, 12.0)", (d,))
        self._ejecutar(dia=AYER)
        serie = self.motor.series_vistas[-1]      # sin términos: solo emoción
        pos = serie.dias.index(degradado)
        self.assertIsNone(serie.valores[pos])     # no medido ≠ 0,0
        self.assertEqual(serie.valores[pos - 1], 0.1)
        # y la elegibilidad del carril llega como dato (D-042), no de la serie
        self.assertIs(self.motor.elegibilidades[-1], True)


class TestScoresSenal(Base):  # §4.5 spec: z_r→z_r, cusum→S_t, mk→p
    def test_tres_metricas_con_sus_scores(self):
        self._siembra_historia()
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("4.5000"), s_cusum=Decimal("6.2500"),
            p_mk=Decimal("0.0100"), alerta=True)
        self._ejecutar(dia=AYER)
        por_metrica = {r["metric"]: r["score"] for r in self._signals(AYER)}
        self.assertEqual(por_metrica, {"z_r": 4.5, "cusum": 6.25, "mk": 0.01})

    def test_metrica_no_computable_sin_fila(self):
        self._siembra_historia()
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("4.5"), s_cusum=Decimal("6.25"), p_mk=None, alerta=True)
        self._ejecutar(dia=AYER)
        metricas = {r["metric"] for r in self._signals(AYER)}
        self.assertEqual(metricas, {"z_r", "cusum"})   # mk None → sin fila


class TestClusterPropagacion(Base):  # mutación (19) · E2
    def _procesa_dia_cluster(self):
        """Siembra 4 docs reales en AYER con vocabulario compartido y los procesa
        con la capa REAL de procesa (detector falso): genera term_stats y las
        filas terms type='cluster' del día, como en producción."""
        from sibila import procesa
        pool = [f"voc{i}" for i in range(24)]
        with db.tx(self.con):
            for i in range(4):
                cuerpo = " ".join(pool[j] for j in range(24) if (j + i) % 4 != 0)
                self._n += 1
                self.con.execute(
                    "INSERT INTO documents(source_id, url_hash, published_at,"
                    " published_at_real, fetched_at, body_text, content_hash, dia)"
                    " VALUES (1, ?, ?, 1, ?, ?, ?, ?)",
                    (f"u{self._n}", f"{AYER}T10:0{i}:00Z", f"{AYER}T11:00:00Z",
                     cuerpo, f"h{self._n}", AYER))

        class DetectorFalso:
            def predict(self, texto, k=1):
                return (["__label__es"], [0.99])
        procesa.ejecutar(self.cfg, self.con, detector=DetectorFalso(), lexicos=None)

    def test_alerta_de_miembro_materializa_cluster(self):
        # historia madura para status confirmado
        self._siembra_historia(dias=30, hasta="2026-08-22", con_term=True)
        self._procesa_dia_cluster()
        n_clusters = self.con.execute(
            "SELECT COUNT(*) FROM terms WHERE type = 'cluster'").fetchone()[0]
        self.assertGreater(n_clusters, 0)   # procesa persistió clústeres del día
        # El fake alerta ante TODO ítem cuyo valor del día es 3 (los voc*:
        # cada uno aparece en 3 de los 4 docs)
        self.motor.regla = lambda s: (
            eval_item(z_r=Decimal("5.0"), s_cusum=Decimal("6.0"),
                      p_mk=Decimal("0.01"), alerta=True)
            if s.valores[-1] == 3.0 else eval_item(z_r=Decimal("1.0")))
        self._ejecutar(dia=AYER)
        filas_cluster = [r for r in self._signals(AYER)
                         if r["target_type"] == "cluster"]
        self.assertTrue(filas_cluster, "el miembro en clúster debe propagar")
        cid = filas_cluster[0]["target_id"]
        self.assertEqual(self.con.execute(
            "SELECT type FROM terms WHERE id = ?", (cid,)).fetchone()[0], "cluster")
        # score = la del miembro disparador (z_r = 5.0)
        self.assertEqual({r["metric"]: r["score"] for r in filas_cluster}["z_r"], 5.0)
        # el clúster NO tiene serie propia (E2)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM term_stats WHERE term_id = ?", (cid,)).fetchone()[0],
            0)

    def test_miembro_sin_cluster_no_propaga(self):
        self._siembra_historia()
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("5.0"), s_cusum=Decimal("6.0"), p_mk=Decimal("0.01"),
            alerta=True)
        self._ejecutar(dia=AYER)
        self.assertEqual([r for r in self._signals(AYER)
                          if r["target_type"] == "cluster"], [])


class TestOpsMetrics(Base):
    def test_las_10_claves_del_dia(self):
        self._siembra_historia()
        self._ejecutar(dia=AYER)
        claves = {r[0] for r in self.con.execute(
            "SELECT DISTINCT clave FROM ops_metrics WHERE clave LIKE 'detecta.%'")}
        self.assertEqual(claves, {f"detecta.{k}" for k in detecta.CLAVES_METRICAS})

    def test_ts_metricas_es_dia_analitico_no_reloj(self):  # rev. D-M3/H-N2 · D-048
        # La inyección de ahora debe ser visible en lo PERSISTIDO: las
        # métricas detecta.* llevan ts = fin del día analítico, JAMÁS el reloj
        # del anfitrión (la mutación ts = db.now_iso() muere aquí).
        self._siembra_historia()
        self._ejecutar(dia=AYER)                 # ahora=HOY simulado
        tss = {r[0] for r in self.con.execute(
            "SELECT ts FROM ops_metrics WHERE clave LIKE 'detecta.%'")}
        self.assertEqual(tss, {f"{AYER}T23:59:59Z"})


class TestConcurrenciaLector(Base):  # trampa 2 · C-B5-5
    def test_lector_mode_ro_y_escritor_fantasma(self):
        self._siembra_historia(dias=30, hasta="2026-08-22")
        for d in ("2026-08-23", "2026-08-24"):
            self._dia(d, 6)
            self._term("crisis", {d: 6})
        errores = []
        parar = threading.Event()

        def lector():  # espejo resumen.py: mode=ro, timeout=30
            uri = f"file:{self.db_path}?mode=ro"
            while not parar.is_set():
                try:
                    con = sqlite3.connect(uri, uri=True, timeout=30)
                    try:
                        con.execute("SELECT COUNT(*) FROM ops_metrics").fetchone()
                    finally:
                        con.close()
                except sqlite3.OperationalError as e:
                    errores.append(e)

        def escritor():
            con = db.connect(self.db_path)
            n = 500
            try:
                while not parar.is_set():
                    try:
                        with db.tx(con):
                            con.execute(
                                "INSERT INTO ops_metrics(ts, clave, valor)"
                                " VALUES ('2026-08-24T00:00:00Z', 'fantasma', ?)",
                                (float(n),))
                            n += 1
                    except sqlite3.OperationalError as e:
                        errores.append(e)
            finally:
                con.close()

        hilos = [threading.Thread(target=lector), threading.Thread(target=escritor)]
        for h in hilos:
            h.start()
        self._ejecutar(desde="2026-08-23", hasta="2026-08-24", ahora=date(2026, 8, 25))
        parar.set()
        for h in hilos:
            h.join()
        self.assertEqual(errores, [])


class TestAvisosRango(Base):  # E3 simétrico · mutación (11)
    def test_reejecutar_dia_ya_evaluado_avisa(self):
        self._siembra_historia(dias=30, hasta="2026-08-22")
        self._dia("2026-08-22", 6)
        self.motor.regla = lambda s: eval_item(
            z_r=Decimal("4.0"), s_cusum=Decimal("5.0"), p_mk=Decimal("0.01"),
            alerta=True)
        self._ejecutar(dia="2026-08-22")   # deja signals del día
        self.motor.regla = lambda s: eval_item(z_r=Decimal("1.0"))
        res = self._ejecutar(dia="2026-08-22")
        self.assertTrue(any("re-ejecutando" in a for a in res["avisos"]))
        # rev. Hamilton M4a: el aviso sugiere retomar el día SIGUIENTE al
        # último ya evaluado (2026-08-23), no re-evaluar el mismo día
        aviso = next(a for a in res["avisos"] if "re-ejecutando" in a)
        self.assertIn("--desde 2026-08-23", aviso)
        self.assertNotIn("--desde 2026-08-22", aviso)

    def test_desde_anterior_al_primer_stats_info_y_clampa(self):
        self._siembra_historia(dias=5, hasta=AYER)   # primer stats = 2026-08-19
        res = self._ejecutar(desde="2026-08-01")
        self.assertTrue(any("sin stats antes de 2026-08-19" in i
                            for i in res["infos"]))
        self.assertEqual(res["dias"][0][0], "2026-08-19")


class TestGuardian(Base):  # C-B5-6
    def test_detecta_es_el_unico_modulo_nuevo_con_db(self):
        raiz = Path(__file__).resolve().parent.parent / "sibila"
        for py in raiz.rglob("*.py"):
            if py.name in ("db.py", "detecta.py", "informe_datos.py", "doctor.py") or "__pycache__" in str(py):  # ro-mode D-B7
                continue
            self.assertNotIn("sqlite3.connect", py.read_text(encoding="utf-8"),
                             f"{py.name} abre conexiones fuera de db.py")

    def test_deteccion_no_importa_db(self):
        import ast
        paq = Path(__file__).resolve().parent.parent / "sibila" / "deteccion"
        if not paq.is_dir():
            self.skipTest("sibila/deteccion aún no existe (agente paralelo)")
        for py in sorted(paq.glob("*.py")):
            arbol = ast.parse(py.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Import):
                    for a in nodo.names:
                        self.assertNotIn(a.name.split(".")[0],
                                         {"sqlite3", "requests"}, py.name)
                if isinstance(nodo, ast.ImportFrom) and nodo.module:
                    raiz = nodo.module.split(".")[0]
                    self.assertNotIn(raiz, {"sqlite3", "requests"}, py.name)
                    if nodo.module in ("sibila", ".."):
                        for a in nodo.names:
                            self.assertNotEqual(a.name, "db", py.name)


class TestHumoCapaReal(Base):
    """TP-N3/TP-N8 extremo a extremo con sibila/deteccion REAL (fachada §3).

    Baseline con VARIANZA (regla congelada: MAD=0 → día ciego, jamás alerta):
    patrón estacionario v(i) = 6 + ((i*3) % 5) − 2 (periodo 5, coprimo con la
    semana 7 → las 4 observaciones del weekday varían, MAD>0; media 6 ≥ 5,
    elegible). Rampa 12/20/30 los 3 últimos días para el ítem 'rampa'.
    Valores recomputados contra la capa real (2026-08-24): documentados abajo.
    """

    def _real(self):
        # Sin skip: el humo corre SIEMPRE contra la capa real (decisión del
        # Orquestador). Un choque de contrato es un FALLO visible, nunca skip.
        from sibila.deteccion import motor, series
        self.assertTrue(hasattr(series, "SerieDiaria") and hasattr(motor, "EvalItem")
                        and hasattr(motor, "evaluar") and hasattr(series, "elegible"),
                        "la capa real no expone la fachada §3 congelada")
        return motor, series

    def test_tp_n3_rampa_confirmada_y_semana_tranquila(self):
        motor, series = self._real()
        ini = date(2026, 6, 20)
        dias = [(ini + timedelta(days=i)).isoformat() for i in range(65)]
        D1, D2, D3 = "2026-08-20", "2026-08-21", "2026-08-22"

        def patron(i):
            return 6 + ((i * 3) % 5) - 2     # 4..8, media 6, MAD>0 por weekday

        for i, d in enumerate(dias):
            self._dia(d, 6)
        plano = {d: float(patron(i)) for i, d in enumerate(dias)}
        rampa = dict(plano)
        # Rampa de 5 días 10/14/19/26/36 (MK exige tendencia para p<0,05; con 3
        # días p_mk=0,1261 y NO hay alerta — la conjunción es la ley).
        rampa["2026-08-19"] = 10.0
        rampa[D1], rampa[D2], rampa[D3] = 14.0, 19.0, 26.0
        rampa["2026-08-23"] = 36.0
        tid_plano = self._term("plano", plano)
        tid_rampa = self._term("rampa", rampa)
        # Días 1-2 con z_r>3: SIN señal (racha < 3); día 3: alerta confirmada.
        # Valores recomputados con la capa real (2026-08-24) sobre esta serie:
        # 08-19 z_r=2,3608 racha=0 · 08-20 z_r=5,7333 racha=1 · 08-21 z_r=8,4313
        # racha=2 · 08-22 z_r=13,8273 racha=3, s_cusum=29,0383, p_mk=0,0214 →
        # alerta. (La baseline con varianza mueve los valores del TP-N3 original,
        # congelado con su propia serie; la conjunción y los umbrales mandan.)
        for d in (D1, D2, D3):
            detecta.ejecutar(self.cfg, self.con, dia=d, ahora=HOY,
                             motor=motor, series=series)
        self.assertEqual(self._signals(D1), [])
        self.assertEqual(self._signals(D2), [])
        sig3 = self._signals(D3)
        self.assertNotIn(tid_plano, {r["target_id"] for r in sig3})
        filas_rampa = [r for r in sig3 if r["target_id"] == tid_rampa]
        self.assertEqual({r["metric"] for r in filas_rampa}, {"z_r", "cusum", "mk"})
        self.assertTrue(all(r["status"] == "confirmado" for r in filas_rampa))
        scores = {r["metric"]: r["score"] for r in filas_rampa}
        self.assertGreater(scores["z_r"], 3.0)
        # Valores EXACTOS recomputados con la capa real (rev. Dijkstra M3: no
        # se quedan en el comentario; una regresión del 4.º decimal muere)
        self.assertEqual(scores["z_r"], float(Decimal("13.8273")))
        self.assertEqual(scores["cusum"], float(Decimal("29.0383")))
        self.assertEqual(scores["mk"], float(Decimal("0.0214")))
        # TP-N8: segunda ejecución del mismo día → resultado idéntico
        antes = [tuple(r) for r in self._signals()]
        zr_antes = [tuple(r) for r in self.con.execute(
            "SELECT day, term_id, z_r FROM term_stats ORDER BY 1, 2")]
        detecta.ejecutar(self.cfg, self.con, dia=D3, ahora=HOY,
                         motor=motor, series=series)
        self.assertEqual(antes, [tuple(r) for r in self._signals()])
        self.assertEqual(zr_antes, [tuple(r) for r in self.con.execute(
            "SELECT day, term_id, z_r FROM term_stats ORDER BY 1, 2")])

    def test_emocion_alerta_con_motor_real(self):  # rev. Dijkstra B1 · D-042
        # Rampa de VALENCE con el motor REAL (sin mocks): la elegibilidad del
        # carril de emoción es dato (gate n_efectivo≥10), nunca la media≥5 de
        # la serie (valence ∈ [−1,1] la haría inalcanzable — la mutación
        # "elegible sobre valence" muere aquí). Debe generarse la fila signals
        # target_type='emocion' con las 3 métricas.
        motor, series = self._real()
        ini = date(2026, 6, 20)
        dias = [(ini + timedelta(days=i)).isoformat() for i in range(65)]

        def patron(i):
            return (6 + ((i * 3) % 5) - 2) / 10   # 0,4..0,8, MAD>0 por weekday

        D1, D2, D3 = "2026-08-20", "2026-08-21", "2026-08-22"
        rampa = {D1[:-2] + "19": 1.0, D1: 1.4, D2: 1.9, D3: 2.6,
                 "2026-08-23": 3.6}
        for i, d in enumerate(dias):
            self._dia(d, 6)
            v = rampa.get(d, patron(i))
            with db.tx(self.con):
                self.con.execute(
                    "INSERT INTO emo_stats(day, lang, valence_mean, arousal_mean,"
                    " n, n_efectivo) VALUES (?, 'es', ?, 0.0, 12, 12.0)", (d, v))
        detecta.ejecutar(self.cfg, self.con, dia=D3, ahora=HOY,
                         motor=motor, series=series)
        tid = self.con.execute(
            "SELECT id FROM terms WHERE text = 'emocion:es' AND type = 'emocion'"
        ).fetchone()[0]
        filas = [r for r in self._signals(D3)
                 if r["target_type"] == "emocion" and r["target_id"] == tid]
        self.assertEqual({r["metric"] for r in filas}, {"z_r", "cusum", "mk"})
        scores = {r["metric"]: r["score"] for r in filas}
        self.assertGreater(scores["z_r"], 3.0)      # recomputado: 13,8272
        self.assertEqual(scores["z_r"], float(Decimal("13.8272")))
        self.assertLess(scores["mk"], 0.05)
        self.assertTrue(all(r["status"] == "confirmado" for r in filas))


if __name__ == "__main__":
    unittest.main()

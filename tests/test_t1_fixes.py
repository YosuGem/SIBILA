"""T1 · fixes de producción D-047 (CC-T1-1/2/3) + inyección `hoy` (plan §2/§6).

(a) TP-N8 básico: re-correr detecta tras alertar NO rompe la FK y conserva
    signals.id; (b) señal referenciada que desaparece → 'descartado' con
    alert_log intacto; (c) no referenciada que desaparece → DELETE;
    (d) batería Bloque 5 verde (se corre en discover). Mordidas en §7 del plan.
"""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sibila import alerta, db, detecta, informe_datos, ingesta, procesa, sella
from tests.test_detecta import SerieDiariaFake  # noqa: F401 (doble de referencia)
from tests.test_sella import HOY as HOY_SELLA, capa_fake as capa_sella_fake

DIA = "2026-06-30"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        self.db_path = self.tmp / "t.db"
        db.init_db(self.db_path)
        self.con = db.connect(self.db_path)
        self.addCleanup(self.con.close)
        self.cfg = SimpleNamespace(data_dir=self.tmp / "datos",
                                   db_path=self.db_path, secretos={})

    def _term_stats(self, dia=DIA, texto="crisis", docs=10, z_r=None):
        with db.tx(self.con):
            self.con.execute("INSERT OR IGNORE INTO terms(text, type) VALUES (?, 'term')",
                             (texto,))
            tid = self.con.execute("SELECT id FROM terms WHERE text = ?",
                                   (texto,)).fetchone()[0]
            self.con.execute(
                "INSERT OR REPLACE INTO term_stats(day, term_id, docs, occ, df, z_r)"
                " VALUES (?, ?, ?, ?, ?, ?)", (dia, tid, docs, docs, docs, z_r))
        return tid

    def _persistir(self, dia=DIA, alerta=True, z_r=4.5, **kw):
        """_persistir_dia directo con una evaluación de term (doble §3 B5)."""
        from decimal import Decimal
        tid = self._term_stats(dia=dia)
        ev = SimpleNamespace(z_r=Decimal("4.5") if z_r is None else Decimal(str(z_r)),
                             s_cusum=Decimal("8.0"), p_mk=Decimal("0.01"))
        item = {"tipo": "term", "term_id": tid}
        cont = {k: 0 for k in detecta.CLAVES_METRICAS}
        return detecta._persistir_dia(self.con, dia, cont, [(item, ev, alerta)],
                                      [], **kw)


class TestCCT11PersistenciaEstable(Base):
    def test_rerun_tras_alerta_conserva_ids_sin_integrity_error(self):
        self._persistir()                                  # signals del día
        sid = self.con.execute("SELECT id FROM signals").fetchone()[0]
        with db.tx(self.con):                              # alerta lo referencia
            self.con.execute(
                "INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                " VALUES (?, 'alerta', 'telegram', '2026-07-01T06:00:00Z')", (sid,))
        self._persistir()                                  # re-corre: UPDATE, no DELETE+INSERT
        ids = [r[0] for r in self.con.execute("SELECT id FROM signals")]
        self.assertIn(sid, ids)
        self.assertEqual(len(self.con.execute(
            "SELECT * FROM alert_log").fetchall()), 1)     # FK intacta

    def test_referenciada_que_desaparece_queda_descartado(self):
        self._persistir()
        sid = self.con.execute("SELECT id FROM signals LIMIT 1").fetchone()[0]
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                " VALUES (?, 'alerta', 'telegram', '2026-07-01T06:00:00Z')", (sid,))
        self._persistir(alerta=False)                      # la señal desaparece
        fila = self.con.execute("SELECT status FROM signals WHERE id = ?",
                                (sid,)).fetchone()
        self.assertEqual(fila[0], "descartado")            # soft-delete, ID vivo
        self.assertEqual(len(self.con.execute(
            "SELECT * FROM alert_log").fetchall()), 1)

    def test_no_referenciada_que_desaparece_se_borra(self):
        self._persistir()
        n0 = self.con.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        self.assertGreater(n0, 0)
        self._persistir(alerta=False)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM signals").fetchone()[0], 0)

    def test_reactivo_siempre_se_conserva(self):           # D-042 intacto
        tid = self._term_stats()
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO signals(day, target_type, target_id, metric, score,"
                " status, created_at) VALUES (?, 'term', ?, 'z_r', 9.0, 'reactivo', ?)",
                (DIA, tid, f"{DIA}T00:00:00Z"))
        self._persistir(alerta=False)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM signals WHERE status = 'reactivo'").fetchone()[0], 1)

    def test_metricas_ts_dia_analitico(self):              # D-047 §2.3
        self._persistir()
        ts = self.con.execute(
            "SELECT DISTINCT substr(ts, 1, 10) FROM ops_metrics"
            " WHERE clave LIKE 'detecta.%'").fetchall()
        self.assertEqual([r[0] for r in ts], [DIA])        # NUNCA el reloj anfitrión


class TestCCT12RachaDerivada(Base):
    """cluster/emocion llegan con racha_z=3 (hecho derivado), no 0."""

    def test_cluster_emocion_clasifican_alerta_no_vigilancia(self):
        from decimal import Decimal
        capa = alerta._capa(None)                          # capa REAL
        for tipo, tema in (("cluster", "cluster:abcdef0123456789"),
                           ("emocion", "emocion:es")):
            ctx = capa.ContextoDia(z_r=Decimal("7.5"), p_mk=Decimal("0.01"),
                                   s_cusum=Decimal("9.0"),
                                   racha_z=alerta.RACHA_DERIVADA_SIGNAL,
                                   status="confirmado", alertas_previas_tema_7d=0)
            senal = capa.Senal(tema=tema, target_type=tipo, status="confirmado",
                               day=date(2026, 7, 2))
            self.assertEqual(capa.clasificar(senal, ctx), "alarma", tipo)

    def test_ejecutar_envia_alarma_de_emocion(self):
        """Señal emocion en signals (sin term_stats de ese target) → alarma
        enviada: con la racha vieja (0) se degradaba a vigilancia (I7)."""
        with db.tx(self.con):
            self.con.execute("INSERT INTO terms(text, type) VALUES ('emocion:es', 'emocion')")
            tid = self.con.execute("SELECT id FROM terms").fetchone()[0]
            for metric, score in (("z_r", 6.0705), ("cusum", 22.2817), ("mk", 0.0102)):
                self.con.execute(
                    "INSERT INTO signals(day, target_type, target_id, metric, score,"
                    " status, created_at) VALUES (?, 'emocion', ?, ?, ?,"
                    " 'confirmado', ?)", (DIA, tid, metric, score, f"{DIA}T00:00:00Z"))
        self.cfg.secretos = {"telegram_token": "t", "telegram_chat": "c"}
        envios = []
        res = alerta.ejecutar(self.cfg, self.con, desde=DIA, hasta=DIA,
                              ahora=datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc),
                              enviar=lambda c, ch, m: envios.append((ch, m)))
        self.assertEqual(res["contadores"]["enviadas"], 1)
        self.assertIn("alarma", envios[0][1])


class TestCCT13ReconciliacionMultiBorrador(Base):
    """Crash multi-borrador (I8): la reconciliación termina 2 líneas, no 3."""

    def test_crash_tras_primer_append_no_duplica(self):
        from tests.helpers.arnes import ahora_del_dia  # solo formato
        capa = capa_sella_fake()
        dia = "2026-08-22"
        # dos señales (term + cluster) y 40 días de historia (madura)
        with db.tx(self.con):
            for texto, tipo in (("crisis", "term"), ("cluster:aa", "cluster")):
                self.con.execute("INSERT INTO terms(text, type) VALUES (?, ?)",
                                 (texto, tipo))
                tid = self.con.execute("SELECT id FROM terms WHERE text = ?",
                                       (texto,)).fetchone()[0]
                self.con.execute(
                    "INSERT INTO signals(day, target_type, target_id, metric, score,"
                    " status, created_at) VALUES (?, ?, ?, 'z_r', 4.5, 'confirmado', ?)",
                    (dia, tipo, tid, f"{dia}T00:00:00Z"))
                self.con.execute(
                    "INSERT INTO term_stats(day, term_id, docs, occ, df)"
                    " VALUES ('2026-07-20', ?, 5, 5, 5)", (tid,))
        ahora = datetime(2026, 8, 23, 6, 0, tzinfo=timezone.utc)
        llamadas = {"n": 0}
        real_insertar = sella._insertar_prediccion

        def falla_en_la_primera(con, linea, madura):
            llamadas["n"] += 1
            if llamadas["n"] == 1:   # crash ENTRE el primer append y su INSERT
                raise RuntimeError("crash tras el primer append")
            return real_insertar(con, linea, madura)
        with mock.patch.object(sella, "_insertar_prediccion", falla_en_la_primera):
            with self.assertRaises(Exception):
                sella.ejecutar(self.cfg, self.con, dia=dia, ahora=ahora, capa=capa)
        # la tx hizo rollback: 0 filas; el fichero conserva 1 línea
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM predictions").fetchone()[0], 0)
        ruta = Path(self.cfg.data_dir) / "registro" / "predicciones.jsonl"
        self.assertEqual(len(ruta.read_bytes().splitlines()), 1)
        # Reanudar SIN mock: reconciliación + dedup → 2 líneas y 2 filas, no 3
        res = sella.ejecutar(self.cfg, self.con, dia=dia, ahora=ahora, capa=capa)
        self.assertEqual(len(ruta.read_bytes().splitlines()), 2)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM predictions").fetchone()[0], 2)
        self.assertEqual(res["contadores"]["reconciliadas"], 1)
        self.assertEqual(res["contadores"]["omitidas"], 1)  # borrador ya vivo
        self.assertEqual(res["contadores"]["selladas"], 1)  # el otro sí se sella


class TestHoyInyectado(Base):  # D-047 §2.3 · C-T1-2 regresión
    def _doc(self, dia, i=0):
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO documents(source_id, url_hash, published_at,"
                " published_at_real, fetched_at, body_text, content_hash, dia)"
                " VALUES (NULL, ?, ?, 1, ?, 'cuerpo con palabras suficientes aqui',"
                " ?, ?)",
                (f"u{dia}{i}", f"{dia}T10:00:00Z", f"{dia}T11:00:00Z",
                 f"h{dia}{i}", dia))

    def test_construir_indice_respeta_hoy(self):
        self._doc("2026-06-30")     # fuera de ventana del reloj anfitrión
        indice_real, _ = procesa.construir_indice(self.con)
        indice_sim, _ = procesa.construir_indice(self.con, hoy=date(2026, 7, 2))
        self.assertGreater(len(indice_sim._firmas), len(indice_real._firmas))

    def test_procesa_con_hoy_estampa_metricas_del_dia(self):
        self._doc(DIA)
        procesa.ejecutar(self.cfg, self.con, dia=DIA, hoy=date(2026, 7, 2))
        ts = self.con.execute(
            "SELECT DISTINCT substr(ts, 1, 10) FROM ops_metrics"
            " WHERE clave LIKE 'procesa.%'").fetchall()
        self.assertEqual([r[0] for r in ts], ["2026-07-02"])

    def test_ingesta_con_hoy_estampa_fetched_at(self):
        from datetime import timezone
        docs = [SimpleNamespace(fuente="t1", url="https://t1.invalid/x/1",
                                author_raw=None,
                                published_at=datetime(2026, 7, 1, 10, 0,
                                                      tzinfo=timezone.utc),
                                body="cuerpo", crudo="c", lang=None)]
        with db.tx(self.con):
            self.con.execute("INSERT INTO sources(nombre, tipo, idioma, peso)"
                             " VALUES ('t1', 'web', 'es', 1.0)")
        conector = SimpleNamespace(nombre="t1", cfg={},
                                   fetch=lambda cfg, cursor: (docs, None))
        ingesta.ingestar(self.cfg, conector, None, self.con,
                         hoy=datetime(2026, 7, 2, 23, 59, 59))
        fetched = self.con.execute("SELECT fetched_at FROM documents").fetchone()[0]
        self.assertEqual(fetched, "2026-07-02T23:59:59Z")

    def test_sin_hoy_comportamiento_intacto(self):   # C-T1-7 regresión
        hoy_real = db.now_iso()[:10]
        self._doc(hoy_real)
        procesa.ejecutar(self.cfg, self.con, dia=hoy_real)
        ts = self.con.execute(
            "SELECT substr(ts, 1, 10) FROM ops_metrics WHERE clave LIKE 'procesa.%'"
            " LIMIT 1").fetchone()[0]
        self.assertEqual(ts, hoy_real)               # reloj real, como siempre


if __name__ == "__main__":
    unittest.main()

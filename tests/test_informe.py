"""T1 · capa de datos de informe.py (plan Liskov Bloque 7 §7/§8, TP-N4/N12).

La capa pura (sibila/informe/render.py) es de Turing y se construye EN PARALELO:
dobles conformes al contrato §5/D-T7 (DatosInforme, render_informe, alertas_fmt).
El humo corre contra la capa real cuando exista (choque → FALLO, nunca skip
silencioso — decisión del Orquestador).
"""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import sqlite3
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sibila import db, informe_datos as informe

HOY = datetime(2026, 8, 24, 6, 0, 0)
DESDE, HASTA = "2026-08-17", "2026-08-23"   # semana ISO 2026-W34


# ---------- Dobles de la capa pura (contrato §5/D-T7) ----------

class DatosInformeFake:
    def __init__(self, **campos):
        self.__dict__.update(campos)


def render_informe_fake(d):
    """Render determinista del doble (7 secciones; n/d cuando falta dato)."""
    return (
        f"# SIBILA — informe {d.dia}\n"
        f"## §1 Cobertura\ndocs: {d.docs} · fuentes: {d.fuentes_on}/"
        f"{d.fuentes_total} · duplicados: {d.dups} · excluidos: {d.excl_fecha}\n"
        f"elegibles {d.elegibles} · ciegos {d.ciegos}\n"
        f"## §2 Tensión\nsube: {d.sube} · baja: {d.baja}\n"
        f"## §4 Emergentes\n{list(d.emergentes)}\n"
        f"## §5 Alertas\n" + "".join(f"- {a}\n" for a in d.alertas) +
        f"## §6 Predicciones\npendientes {d.pend} (inmaduras {d.pend_inm}) · "
        f"resueltas {d.resueltas}\n"
        f"## §7 Referencia GDELT\n{d.gdelt}\n"
    )


def alertas_fmt_fake(senal, nivel, etiquetas, **kw):
    etiqueta = etiquetas.get(senal["tema"], senal["tema"])
    return f"{senal['day']} {nivel}: {etiqueta} [{senal['status']}]"


def capa_informe_fake():
    return SimpleNamespace(DatosInforme=DatosInformeFake,
                           render_informe=render_informe_fake,
                           render_csv=None, render_json=None,
                           alertas_fmt=alertas_fmt_fake,
                           INFORME_VERSION="informe-1-test")


class EspiaSQL:
    """Proxy de conexión que registra todo SQL (espía de conexión ro)."""

    def __init__(self, con):
        self._con = con
        self.sql = []

    def execute(self, sql, *a, **k):
        self.sql.append(sql)
        return self._con.execute(sql, *a, **k)

    def __getattr__(self, nombre):
        return getattr(self._con, nombre)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        self.db_path = self.tmp / "t.db"
        db.init_db(self.db_path)
        self.cfg = SimpleNamespace(data_dir=self.tmp / "datos")
        (self.tmp / "datos").mkdir()
        self.con = db.connect(self.db_path)   # siembra con conexión normal
        self.addCleanup(self.con.close)
        with db.tx(self.con):
            for i in (1, 2, 3):
                self.con.execute("INSERT INTO sources(nombre, peso) VALUES (?, 1.0)",
                                 (f"f{i}",))
        self.capa = capa_informe_fake()

    def _ro(self):
        return informe.conectar_ro(self.db_path)

    def _doc(self, dia=HASTA, fuente=1, dup=False, sin_fecha=False):
        self._n = getattr(self, "_n", 0) + 1
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO documents(source_id, url_hash, published_at,"
                " published_at_real, fetched_at, body_text, content_hash, dia)"
                " VALUES (?, ?, ?, ?, ?, 'cuerpo', ?, ?)",
                (fuente, f"u{self._n}", None if sin_fecha else f"{dia}T10:00:00Z",
                 0 if sin_fecha else 1, f"{dia}T11:00:00Z", f"h{self._n}",
                 None if sin_fecha else dia))

    def _senal(self, dia=HASTA, tema="crisis", metric="z_r", score=4.5,
               status="confirmado"):
        with db.tx(self.con):
            self.con.execute("INSERT OR IGNORE INTO terms(text, type) VALUES (?, 'term')",
                             (tema,))
            tid = self.con.execute("SELECT id FROM terms WHERE text = ?",
                                   (tema,)).fetchone()[0]
            self.con.execute(
                "INSERT INTO signals(day, target_type, target_id, metric, score,"
                " status, created_at) VALUES (?, 'term', ?, ?, ?, ?, ?)",
                (dia, tid, metric, score, status, f"{dia}T00:00:00Z"))
        return tid

    def _fuentes_toml(self, habilitadas=3, total=4):
        lineas = []
        for i in range(total):
            hab = "true" if i < habilitadas else "false"
            lineas.append(f'[f{i}]\ntipo = "rss"\nurl = "http://x/{i}"\n'
                          f'habilitada = {hab}\n')
        (self.tmp / "datos" / "fuentes.toml").write_text("\n".join(lineas),
                                                         encoding="utf-8")

    def _ejecutar(self, **kw):
        kw.setdefault("desde", DESDE)
        kw.setdefault("hasta", HASTA)
        kw.setdefault("ahora", HOY)
        kw.setdefault("capa", self.capa)
        con = kw.pop("con", None) or self._ro()
        try:
            return informe.ejecutar(self.cfg, con, **kw)
        finally:
            con.close()


class TestRoPuro(Base):  # C-B7-1 · TP-N4 · trampa 1
    def test_conexion_ro_no_escribe(self):
        con = self._ro()
        self.addCleanup(con.close)
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("INSERT INTO ops_metrics(ts, clave, valor) VALUES ('x', 'y', 1)")

    def test_ejecutar_no_modifica_la_bd_bit_a_bit(self):
        for i in range(3):
            self._doc()
        self._senal()
        antes = self.db_path.read_bytes()
        self._ejecutar()
        self.assertEqual(self.db_path.read_bytes(), antes)   # TP-N4 de datos

    def test_espia_sql_jamas_selecciona_author_hash(self):  # spec §6.8/§9
        self._doc()
        self._senal()
        con = EspiaSQL(self._ro())
        informe.ejecutar(self.cfg, con, desde=DESDE, hasta=HASTA, ahora=HOY,
                         capa=self.capa)
        todo = " ".join(con.sql).lower()
        self.assertNotIn("author_hash", todo)
        self.assertTrue(con.sql)   # el espía realmente vio consultas


class TestExtraccion(Base):
    def test_cobertura_y_fuentes_3_4(self):  # M2: fuentes_total desde fuentes.toml
        self._fuentes_toml()
        for i in range(5):
            self._doc(fuente=1 + i % 3)
        self._doc(dup=True)      # published dup marcado a mano abajo
        with db.tx(self.con):
            self.con.execute("UPDATE documents SET duplicate_of = 1 WHERE id = 6")
        self._doc(sin_fecha=True)
        r = self._ejecutar()
        c = r["contenido"]
        self.assertIn("docs: 6", c)        # el sin-fecha tiene dia NULL (excluido)
        self.assertIn("fuentes: 3/3", c)
        self.assertIn("duplicados: 1", c)
        self.assertIn("excluidos: 1", c)

    def test_fuentes_toml_ausente_es_degradado_no_cero(self):  # rev. Dijkstra M4
        self._doc()
        r = self._ejecutar()
        # ausente → "n/d" (degradado visible), JAMÁS "1/0" (0 ≠ desconocido)
        self.assertIn("fuentes: 1/n/d", r["contenido"])

    def test_gdelt_sin_fila_es_nd(self):  # TP-N12
        self._doc()
        r = self._ejecutar()
        self.assertIn("n/d", r["contenido"])

    def test_gdelt_con_fila(self):
        self._doc()
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO gdelt_ref(tema, day, n, fetched_at)"
                " VALUES ('crisis', ?, 320, '2026-08-23T00:00:00Z')", (HASTA,))
        r = self._ejecutar()
        self.assertIn("320 titulares (crisis)", r["contenido"])

    def test_emocion_null_no_rompe_la_extraccion(self):  # residual R1 D-042
        # la extracción del informe NO lee emo_stats (DatosInforme congelado no
        # tiene campo emoción); una fila con valence NULL no debe romper nada
        self._doc()
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO emo_stats(day, lang, valence_mean, arousal_mean, n,"
                " n_efectivo) VALUES (?, 'es', NULL, NULL, 3, 12.0)", (HASTA,))
        r = self._ejecutar()
        self.assertIn("informe", r["contenido"])

    def test_tension_sube_baja_y_emergentes(self):
        self._doc()
        with db.tx(self.con):
            for texto, zr in (("caliente", 4.5), ("fria", -2.5), ("neutra", 0.1)):
                self.con.execute("INSERT INTO terms(text, type) VALUES (?, 'term')",
                                 (texto,))
                tid = self.con.execute("SELECT id FROM terms WHERE text = ?",
                                       (texto,)).fetchone()[0]
                self.con.execute(
                    "INSERT INTO term_stats(day, term_id, docs, occ, df, z_r)"
                    " VALUES (?, ?, 5, 5, 5, ?)", (HASTA, tid, zr))
        r = self._ejecutar()
        self.assertIn("'caliente', '4.5000'", r["contenido"])
        self.assertIn("'fria', '-2.5000'", r["contenido"])
        self.assertIn("'caliente'", r["contenido"])   # emergente (primer día en rango)

    def test_alertas_formateadas_con_linea_viva(self):  # D-T7-8
        self._doc()
        self._senal(score=4.5)                         # z_r 4.5 < 6 → alerta
        self._senal(tema="tension", metric="z_r", score=7.5)  # ≥6 → alarma
        sid = self.con.execute(
            "SELECT MAX(s.id) FROM signals s JOIN terms t ON t.id = s.target_id"
            " WHERE t.text = 'tension'").fetchone()[0]
        with db.tx(self.con):  # tension se notificó como alarma (z_r 7.5 real)
            self.con.execute(
                "INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                " VALUES (?, 'alarma', 'telegram', ?)", (sid, f"{HASTA}T06:00:00Z"))
        r = self._ejecutar()
        self.assertIn(f"{HASTA} alerta: crisis [confirmado]", r["contenido"])
        self.assertIn(f"{HASTA} alarma: tension [confirmado]", r["contenido"])
        self.assertEqual(r["n_alertas"], 2)

    def test_predicciones_desde_la_tabla(self):  # D-044
        with db.tx(self.con):
            for i, (estado, madura) in enumerate((("pendiente", 1),
                                                  ("pendiente", 0),
                                                  ("cumplida", 1))):
                self.con.execute(
                    "INSERT INTO predictions(tema, metrica, umbral, ventana,"
                    " criterio_acierto, created_at, hash, prev_hash, estado, madura)"
                    " VALUES (?, 'z_r', '1.0', 'P30D', 'x', ?, ?, '00', ?, ?)",
                    (f"t{i}", f"{HASTA}T00:00:00Z", f"h{i}", estado, madura))
        r = self._ejecutar()
        self.assertIn("pendientes 3 (inmaduras 1) · resueltas 1", r["contenido"])


class TestFichero(Base):  # trampa 14 · A-B7-1
    def test_escritura_atomica_y_meta_hermano(self):
        r = self._ejecutar()
        ruta = self.tmp / "informe.md"
        informe.escribir_fichero(ruta, r["contenido"], r["meta"])
        self.assertEqual(ruta.read_bytes(), r["contenido"].encode("utf-8"))
        import json
        meta = json.loads((self.tmp / "informe.md.meta.json").read_text("utf-8"))
        self.assertEqual(meta["renderer"], "informe-1-test")
        self.assertEqual(meta["rango"], [DESDE, HASTA])
        self.assertFalse((self.tmp / "informe.md.tmp").exists())

    def test_fallo_de_disco_no_deja_informe_a_medias(self):
        r = self._ejecutar()
        ruta = self.tmp / "informe.md"
        real = Path.write_bytes

        def escribe_a_medias(self_, datos):  # crash a mitad de la escritura
            real(self_, bytes(datos[:10]))
            raise OSError("disco lleno")
        with mock.patch.object(Path, "write_bytes", escribe_a_medias):
            with self.assertRaises(informe.InformeError):
                informe.escribir_fichero(ruta, r["contenido"], r["meta"])
        self.assertFalse(ruta.exists())              # jamás un informe a medias
        self.assertFalse((self.tmp / "informe.md.tmp").exists())

    def test_byte_exacto_dos_ejecuciones_mismo_ahora(self):  # TP-N4/vector (i)
        self._doc()
        self._senal()
        r1 = self._ejecutar()
        r2 = self._ejecutar()
        self.assertEqual(r1["contenido"], r2["contenido"])

    def test_semana_iso_lunes_domingo(self):
        self.assertEqual(informe.semana_iso(date(2026, 8, 23)),
                         ("2026-08-17", "2026-08-23"))

    def test_items_ciegos_clave_real_ops_metrics(self):  # rev. Dijkstra B1        # La clave REAL es detecta.items_ciego (renombrada en B5-R2): sembrada
        # debe llegar al informe; la obsoleta (dias_ciego) ya no alimenta nada.
        self._doc()
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO ops_metrics(ts, clave, valor)"
                " VALUES (?, 'detecta.items_ciego', 2)", (f"{HASTA}T12:00:00Z",))
        self.assertIn("ciegos 2", self._ejecutar()["contenido"])
        with db.tx(self.con):
            self.con.execute("DELETE FROM ops_metrics")
            self.con.execute(
                "INSERT INTO ops_metrics(ts, clave, valor)"
                " VALUES (?, 'detecta.dias_ciego', 3)", (f"{HASTA}T12:00:00Z",))
        self.assertIn("ciegos 0", self._ejecutar()["contenido"])

    def test_senal_descartada_no_aparece_en_informe(self):  # rev. Hamilton N1
        # CC-T1-1: 'descartado' queda fuera del informe (informe_datos:170).
        # La mutación (incluir 'descartado' en el IN) la haría aparecer.
        self._doc()
        self._senal(tema="crisis", status="confirmado")
        self._senal(tema="fantasma", status="descartado")
        lineas = informe._alertas(self.con, DESDE, HASTA, self.capa, {})
        self.assertTrue(any("crisis" in l for l in lineas))
        self.assertFalse(any("fantasma" in l for l in lineas))

    def test_nivel_mostrado_es_el_notificado(self):  # T2: nivel real de alert_log
        # La línea del informe muestra el NIVEL AL QUE SE NOTIFICÓ (último
        # alert_log de la señal), no una reclasificación; sin envío → 'alerta'
        # (fallback documentado). Un "nivel inventado" mutante moriría aquí.
        self._senal(tema="crisis")                       # sin alert_log → alerta
        self._senal(tema="tension")                      # con envío a alarma
        sid = self.con.execute(
            "SELECT MAX(s.id) FROM signals s JOIN terms t ON t.id = s.target_id"
            " WHERE t.text = 'tension'").fetchone()[0]
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                " VALUES (?, 'alarma', 'telegram', ?)", (sid, f"{HASTA}T06:00:00Z"))
        lineas = informe._alertas(self.con, DESDE, HASTA, self.capa, {})
        self.assertTrue(any("alerta: crisis" in l for l in lineas))
        self.assertTrue(any("alarma: tension" in l for l in lineas))
        # un fallo NO fija nivel (canal fallo: queda fuera, B1)
        self._senal(tema="roto")
        sid2 = self.con.execute(
            "SELECT MAX(s.id) FROM signals s JOIN terms t ON t.id = s.target_id"
            " WHERE t.text = 'roto'").fetchone()[0]
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                " VALUES (?, 'alarma', 'fallo:telegram', ?)", (sid2, f"{HASTA}T06:00:00Z"))
        lineas = informe._alertas(self.con, DESDE, HASTA, self.capa, {})
        self.assertTrue(any("alerta: roto" in l for l in lineas))

    def test_conexion_ro_timeout_30s(self):  # rev. Hamilton M2
        with mock.patch.object(informe.sqlite3, "connect",
                               wraps=informe.sqlite3.connect) as esp:
            con = self._ro()
            self.addCleanup(con.close)
        self.assertEqual(esp.call_args.kwargs["timeout"], 30)  # literal (H2)


class TestHumoCapaReal(Base):
    """Vector (i) del informe contra la capa REAL (sin skip: choque → FALLO)."""

    def _real(self):
        try:
            from sibila.informe import render as rr
            from sibila.alertas import reglas
        except ImportError as e:
            self.skipTest(f"capa pura aún no entregada: {e}")
        self.assertTrue(hasattr(rr, "DatosInforme") and hasattr(rr, "render_informe"),
                        "fachada informe rota (contrato §5/D-T7)")
        return informe._capa(None)

    def test_vector_i_byte_exacto_si_hay_fachada(self):
        capa = self._real()
        self._fuentes_toml()
        for i in range(3):
            self._doc()
        self._senal(score=4.5)
        r1 = self._ejecutar(capa=capa)
        r2 = self._ejecutar(capa=capa)
        self.assertEqual(r1["contenido"], r2["contenido"])   # determinista
        self.assertIn("informe", r1["contenido"].lower())

    def test_anomalias_incluyen_dias_anomalos_de_detecta(self):  # rev. Dijkstra M3
        # D-T7-5: días parciales/huecos/ciegos del período son anomalía.
        capa = self._real()
        self._doc()
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO ops_metrics(ts, clave, valor) VALUES"
                " (?, 'detecta.dia_parcial', 1), (?, 'detecta.dia_hueco', 1),"
                " (?, 'detecta.items_ciego', 3)",
                (f"{HASTA}T12:00:00Z",) * 3)
        c = self._ejecutar(capa=capa)["contenido"]
        self.assertIn("dia parcial detectado", c)
        self.assertIn("dia hueco detectado", c)
        # la línea de ciegos fue RETIRADA en T2: el vector (i) congelado
        # exige ciegos=2 con anomalias=() (byte-exacto 13a45d3e/beb32a52);
        # los ciegos siguen visibles en §1 cobertura
        self.assertIn("items ciegos: 3", c)
        self.assertNotIn("items ciegos en el periodo", c)

    def test_render_rechaza_cualquier_campo_none(self):  # rev. Dijkstra M6
        # No solo dia/gdelt: docs=None (o cualquier obligatorio) es ValueError,
        # jamás "None" renderizado en silencio.
        import dataclasses
        from sibila.informe import render as rr
        d = rr.DatosInforme(
            dia="2026-08-23", docs=1, fuentes_on=1, fuentes_total=1, dups=0,
            excl_fecha=0, elegibles=0, ciegos=0, parcial=False, hueco=False,
            inmaduro=False, sube=(), baja=(), emergentes=(), alertas=(),
            anomalias=(), pend=0, pend_inm=0, resueltas=0, gdelt="n/d")
        for campo in ("docs", "fuentes_on", "dups", "elegibles", "ciegos",
                      "pend", "gdelt", "sube"):
            with self.assertRaises(ValueError, msg=campo):
                rr.render_informe(dataclasses.replace(d, **{campo: None}))

    def test_tension_cluster_con_prefijo_no_hex_crudo(self):  # rev. Dijkstra M7
        # Una fila type='cluster' en Tensión se etiqueta 'cluster:{hex16}'
        # (mapeable/anotable por el render), JAMÁS el hex crudo de 64 chars.
        capa = self._real()
        self._doc()
        hexkey = "ab" * 32
        with db.tx(self.con):
            self.con.execute("INSERT INTO terms(text, type) VALUES (?, 'cluster')",
                             (hexkey,))
            tid = self.con.execute("SELECT id FROM terms WHERE text = ?",
                                   (hexkey,)).fetchone()[0]
            self.con.execute(
                "INSERT INTO term_stats(day, term_id, docs, occ, df, z_r)"
                " VALUES (?, ?, 5, 5, 5, 9.0)", (HASTA, tid))
        c = self._ejecutar(capa=capa)["contenido"]
        self.assertIn("cluster:" + "ab" * 8, c)          # prefijo + hex16
        self.assertNotIn(hexkey, c)                       # hex crudo NO
        self.assertIn("cluster sin etiqueta", c)          # anotado (T-B7-10)


if __name__ == "__main__":
    unittest.main()

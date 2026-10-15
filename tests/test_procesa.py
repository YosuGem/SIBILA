"""T1 · capa de datos de procesa.py (plan Liskov §10, tests 1-16, 18-22).

Modo degradado REAL del sandbox: detector de idioma inyectado como doble
(lid.176.ftz no existe) y léxicos NRC de fixtures (verificar_sha=False) salvo
que el test diga lo contrario. BD siempre en archivo real bajo directorio con
espacio y acentos (trampa T3 global).
"""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sibila import db, procesa
from sibila.procesado import bot_heur
from sibila.procesado.bot_heur import BOT_VERSION
from sibila.procesado.emocion import cargar_lexicos

FIX = Path(__file__).parent / "fixtures" / "procesado"
CFG_LEX = {"nrc_vad_en": FIX / "vad_en.txt", "nrc_vad_es": FIX / "vad_es.txt",
           "nrc_emociones_en": FIX / "emo_en.txt", "nrc_emociones_es": FIX / "emo_es.txt"}

# Texto ES cuyo vector de emoción casa con el mini-léxico fixture (ver
# test_procesado_emocion.py): casadas = alegria, confianza, sorpresa.
TEXTO_EMO = "la alegria y la confianza llenan la fiesta de sorpresa"


class DetectorFalso:
    """Doble del detector fastText: detectar() real decide con su predict()."""

    def __init__(self, lang="es", conf=0.99):
        self._label = f"__label__{lang}"
        self._conf = conf

    def predict(self, texto, k=1):
        return ([self._label], [self._conf])


def _lex():
    return cargar_lexicos(CFG_LEX, verificar_sha=False)


class CfgFalsa:
    """cfg mínima: data_dir sin recursos (los tests inyectan detector/léxicos)."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)


def texto_largo(semilla="crisis", n=80):
    """Texto con ≥50 content words (simhash no NULL) y variado."""
    return " ".join(f"{semilla}{i} palabra{i % 13} dato{i % 7}" for i in range(n))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        self.db_path = self.tmp / f"test_{self._testMethodName}.db"
        db.init_db(self.db_path)
        self.con = db.connect(self.db_path)
        self.addCleanup(self.con.close)
        self.cfg = CfgFalsa(self.tmp / "sin recursos")
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO sources(nombre, tipo, peso) VALUES ('f1', 'rss', 1.0)")
            self.con.execute(
                "INSERT INTO sources(nombre, tipo, peso) VALUES ('f2', 'rss', 0.5)")
        self.det = DetectorFalso()

    def _doc(self, body="texto breve", *, fuente=1, dia="2026-08-20",
             pub="2026-08-20T10:00:00Z", autor=None, url=None, chash=None):
        """Inserta un doc crudo tal como lo deja ingesta (campos de procesado NULL)."""
        self._n = getattr(self, "_n", 0) + 1
        n = self._n
        real = 1 if pub is not None else 0
        with db.tx(self.con):
            cur = self.con.execute(
                "INSERT INTO documents(source_id, url_hash, author_hash, published_at,"
                " published_at_real, fetched_at, body_text, content_hash, dia)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fuente, url or f"u{n}", autor, pub, real,
                 "2026-08-20T11:00:00Z", body, chash or f"h{n}", dia if real else None))
        return cur.lastrowid

    def _ejecutar(self, **kw):
        kw.setdefault("detector", self.det)
        kw.setdefault("lexicos", _lex())
        return procesa.ejecutar(self.cfg, self.con, **kw)

    def _fila(self, doc_id):
        return self.con.execute("SELECT * FROM documents WHERE id = ?",
                                (doc_id,)).fetchone()

    def _dump(self):
        """Volcado comparable de las tablas que escribe procesa (sin ops ts)."""
        out = {}
        for t, cols in (("documents", "lang, simhash, duplicate_of, calidad_score,"
                                     " bot_flags, bot_detector_version, peso, dia"),
                        ("terms", "text, type, cluster_key"),
                        ("term_stats", "day, term_id, docs, occ, df, z_r"),
                        ("emo_stats", "day, lang, valence_mean, arousal_mean, n, n_efectivo")):
            out[t] = self.con.execute(f"SELECT {cols} FROM {t} ORDER BY 1, 2").fetchall()
        out["ops"] = self.con.execute(
            "SELECT clave, valor FROM ops_metrics ORDER BY clave, valor").fetchall()
        return out


class TestPendientes(Base):  # §10.1
    def test_solo_null_o_version_distinta(self):
        a = self._doc()                                   # pendiente (todo NULL)
        b = self._doc()                                   # se marca procesado a mano
        with db.tx(self.con):
            self.con.execute(
                "UPDATE documents SET calidad_score = 0.5, bot_detector_version = ?"
                " WHERE id = ?", (BOT_VERSION, b))
        c = self._doc()                                   # versión vieja → pendiente
        with db.tx(self.con):
            self.con.execute(
                "UPDATE documents SET calidad_score = 0.5, bot_detector_version = 'bot-0'"
                " WHERE id = ?", (c,))
        ids = [f["id"] for f in procesa.pendientes(self.con, BOT_VERSION,
                                                   dia=None, todo=False, limite=None)]
        self.assertEqual(ids, [a, c])                     # orden id ASC
        ids_todo = [f["id"] for f in procesa.pendientes(
            self.con, BOT_VERSION, dia=None, todo=True, limite=None)]
        self.assertEqual(ids_todo, [a, b, c])

    def test_procesado_no_reaparece(self):
        self._doc(body=texto_largo())
        self._ejecutar()
        res = self._ejecutar()
        self.assertEqual(res["pendientes"], 0)


class TestMarcaCalidad(Base):  # §10.2 · trampa 2
    def test_doc_corto_simhash_null_pero_procesado(self):
        d = self._doc(body="solo tres palabras")
        res = self._ejecutar()
        f = self._fila(d)
        self.assertIsNone(f["simhash"])                   # <50 content words
        self.assertIsNotNone(f["calidad_score"])          # marca SIEMPRE escrita
        self.assertEqual(res["pendientes"], 1)
        self.assertEqual(self._ejecutar()["pendientes"], 0)  # no reaparece


class TestLoteAtomico(Base):  # §10.3
    def test_rollback_total_del_lote(self):
        ids = [self._doc(body=texto_largo(f"t{i}")) for i in range(4)]
        antes = self._dump()

        def rompe_alta(con, texto, tipo, cluster_key=None):
            raise sqlite3.IntegrityError("CHECK roto a mitad de la fase BD")
        with mock.patch.object(procesa, "_alta_term", rompe_alta):
            with self.assertRaises(procesa.ProcesaError):
                self._ejecutar()
        despues = self._dump()
        self.assertEqual(antes, despues)                  # sin rastro del lote
        for d in ids:
            self.assertIsNone(self._fila(d)["calidad_score"])

    def test_interrupcion_entre_lotes(self):  # §10.4
        [self._doc(body=texto_largo(f"a{i}"), dia="2026-08-20") for i in range(2)]
        [self._doc(body=texto_largo(f"b{i}"), dia="2026-08-21") for i in range(2)]
        real_recalc = procesa.recalcular_dias

        def rompe_en_segundo(con, dias, lex, ts=None):
            if "2026-08-21" in dias:
                raise sqlite3.OperationalError("corte en el lote 2")
            return real_recalc(con, dias, lex, ts=ts)
        with mock.patch.object(procesa, "recalcular_dias", rompe_en_segundo):
            with self.assertRaises(procesa.ProcesaError):
                self._ejecutar(lote=2)
        # Lote 1 íntegro y consistente: docs procesados CON sus stats del día
        n_proc = self.con.execute(
            "SELECT COUNT(*) FROM documents WHERE calidad_score IS NOT NULL").fetchone()[0]
        self.assertEqual(n_proc, 2)
        n_stats = self.con.execute(
            "SELECT COUNT(*) FROM term_stats WHERE day = '2026-08-20'").fetchone()[0]
        self.assertGreater(n_stats, 0)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM term_stats WHERE day = '2026-08-21'").fetchone()[0], 0)


class TestIdempotencia(Base):  # §10.5 · C-B4-2
    def test_dos_ejecuciones_bit_a_bit(self):
        for i in range(6):
            self._doc(body=texto_largo(f"x{i}") + " " + TEXTO_EMO,
                      dia=f"2026-08-{20 + i % 3}")
        self._ejecutar()
        primero = self._dump()
        res = self._ejecutar()
        self.assertEqual(res["pendientes"], 0)
        self.assertEqual(primero, self._dump())


class TestZrConservado(Base):  # §10.6 · trampa 3
    def test_upsert_no_toca_zr(self):
        self._doc(body=texto_largo("z"), dia="2026-08-20")
        self._ejecutar()
        with db.tx(self.con):  # "detecta" escribe z_r en TODAS las filas del día
            self.con.execute("UPDATE term_stats SET z_r = 5.0 WHERE day = '2026-08-20'")
        n5 = self.con.execute(
            "SELECT COUNT(*) FROM term_stats WHERE day = '2026-08-20'"
            " AND z_r = 5.0").fetchone()[0]
        self.assertGreater(n5, 0)
        self._doc(body=texto_largo("z2"), dia="2026-08-20")
        self._ejecutar()  # recalcula el día completo
        despues5 = self.con.execute(
            "SELECT COUNT(*) FROM term_stats WHERE day = '2026-08-20'"
            " AND z_r = 5.0").fetchone()[0]
        self.assertEqual(despues5, n5)             # z_r JAMÁS machacado (trampa 3)
        nuevos_null = self.con.execute(
            "SELECT COUNT(*) FROM term_stats ts JOIN terms t ON t.id = ts.term_id"
            " WHERE ts.day = '2026-08-20' AND ts.z_r IS NULL"
            " AND t.text LIKE '%z2%'").fetchone()[0]
        self.assertGreater(nuevos_null, 0)         # términos nuevos entran con NULL


class TestTermsEstables(Base):  # §10.7 · V2
    def test_mismo_termino_mismo_id(self):
        self._doc(body=texto_largo("alfa"), dia="2026-08-20")
        self._doc(body=texto_largo("alfa"), dia="2026-08-21")
        self._ejecutar()
        ids = [r[0] for r in self.con.execute(
            "SELECT id FROM terms WHERE text LIKE 'alfa%'")]
        self.assertEqual(len(ids), len(set(ids)))
        antes = dict(self.con.execute("SELECT text, id FROM terms").fetchall())
        self._ejecutar()
        despues = dict(self.con.execute("SELECT text, id FROM terms").fetchall())
        self.assertEqual(antes, despues)

    def test_cluster_key_estable_y_sensible_a_miembros(self):
        # 4 docs con vocabulario compartido (df≥3, co-ocurrencia≥3) pero texto
        # suficientemente distinto para no ser near-dup ni republicación.
        pool = [f"voc{i}" for i in range(24)]
        for i in range(4):
            cuerpo = " ".join(pool[j] for j in range(24) if (j + i) % 4 != 0)
            self._doc(body=cuerpo + f" relleno{i} " * 3, dia="2026-08-20")
        self._ejecutar()
        claves = [r[0] for r in self.con.execute(
            "SELECT cluster_key FROM terms WHERE type = 'cluster' ORDER BY cluster_key")]
        self.assertTrue(claves)
        self._ejecutar()  # re-ejecución: mismas claves
        self.assertEqual(claves, [r[0] for r in self.con.execute(
            "SELECT cluster_key FROM terms WHERE type = 'cluster' ORDER BY cluster_key")])
        self._doc(body=" ".join(pool) + " terminonuevodistinto", dia="2026-08-20")
        self._ejecutar()
        despues = {r[0] for r in self.con.execute(
            "SELECT cluster_key FROM terms WHERE type = 'cluster'")}
        self.assertTrue(set(claves) <= despues)  # alta idempotente, sin duplicar


class TestExclusionFecha(Base):  # §10.8 · C-B4-3
    def test_published_at_real_0_excluido_con_contador(self):
        d = self._doc(body=texto_largo("sinfecha"), pub=None)
        self._doc(body=texto_largo("confecha"), dia="2026-08-20")
        res = self._ejecutar()
        f = self._fila(d)
        self.assertIsNotNone(f["calidad_score"])   # procesado…
        self.assertIsNone(f["dia"])
        term_ids = [r[0] for r in self.con.execute(
            "SELECT id FROM terms WHERE text LIKE 'sinfecha%'")]
        self.assertTrue(term_ids)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM term_stats WHERE term_id IN (%s)"
            % ",".join("?" * len(term_ids)), term_ids).fetchone()[0], 0)
        self.assertEqual(res["contadores"]["excluidos_fecha"], 1)


class TestPesoRecomputado(Base):  # §10.9 · D-B4-03 / trampa 1
    def test_dos_flags_peso_025_y_estable(self):
        body = ("lo siento, pero no puedo ayudarte con eso. "  # marcador
                + "eco repetitivo " * 30)                     # plantilla (2 trigramas)
        d = self._doc(body=body, dia="2026-08-20")
        self._ejecutar()
        f = self._fila(d)
        flags = json.loads(f["bot_flags"])
        self.assertTrue(flags["marcador"])
        self.assertTrue(flags["plantilla"])
        self.assertAlmostEqual(f["peso"], 0.25)
        # Re-ejercicio con --todo: RECOMPUTO, jamás 0.125 (trampa 1)
        self._ejecutar(todo=True)
        self.assertAlmostEqual(self._fila(d)["peso"], 0.25)


class TestReVersionado(Base):  # §10.10 · C-B4-4
    def test_subir_bot_version_reprocesa_sin_duplicar(self):
        self._doc(body=texto_largo("v1"), dia="2026-08-20")
        self._doc(body=texto_largo("v2"), dia="2026-08-20")
        self._ejecutar()
        terms_antes = self.con.execute("SELECT COUNT(*) FROM terms").fetchone()[0]
        stats_antes = self.con.execute("SELECT COUNT(*) FROM term_stats").fetchone()[0]
        with mock.patch.object(procesa.bot_heur, "BOT_VERSION", "bot-2"):
            res = self._ejecutar()
        self.assertEqual(res["pendientes"], 2)     # ambos re-procesados
        for r in self.con.execute("SELECT bot_detector_version FROM documents"):
            self.assertEqual(r[0], "bot-2")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM terms").fetchone()[0],
                         terms_antes)              # UNIQUEs intactos
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM term_stats").fetchone()[0],
                         stats_antes)


class TestNearDup(Base):  # §10.11 y §10.13
    def test_intra_fuente_apunta_al_menor_y_determinista(self):
        base = texto_largo("nd", 80)
        ids = [self._doc(body=base, fuente=1, dia="2026-08-20") for _ in range(3)]
        # copia con UNA palabra distinta: hamming pequeño
        copia = base.replace("nd0 palabra0", "distinta0 palabra0", 1)
        ids.append(self._doc(body=copia, fuente=1, dia="2026-08-20"))
        self._ejecutar()
        dups = {r["id"]: r["duplicate_of"] for r in self.con.execute(
            "SELECT id, duplicate_of FROM documents ORDER BY id")}
        self.assertIsNone(dups[ids[0]])
        for d in ids[1:]:
            self.assertEqual(dups[d], ids[0])      # MIN(id), trampa 5
        self._ejecutar(todo=True)                  # re-ejecutar → igual
        dups2 = {r["id"]: r["duplicate_of"] for r in self.con.execute(
            "SELECT id, duplicate_of FROM documents ORDER BY id")}
        self.assertEqual(dups, dups2)

    def test_cross_fuente_no_es_near_dup_simhash(self):
        base = texto_largo("xf", 80)
        a = self._doc(body=base, fuente=1, dia="2026-08-20")
        copia = base.replace("xf0 palabra0", "otra0 palabra0", 1)
        b = self._doc(body=copia, fuente=2, dia="2026-08-20")
        res = self._ejecutar()
        # inter-fuente no entra por simhash; puede salir por minhash (republicado)
        self.assertEqual(res["contadores"]["near_dup"], 0)

    def test_hamming_entre_4_y_10_no_es_dup(self):  # rev. Hamilton M3
        # Par MISMA fuente con hamming ∈ [4,10]: NO es near-dup (umbral ≤3).
        # Test NEGATIVO: la mutación `<= 3` → `<= 10` debe morir aquí.
        base = texto_largo("nh", 80)
        copia = base
        for i in range(6):   # 6 palabras cambiadas → hamming 5 (verificado)
            copia = copia.replace(f"nh{i * 3} palabra", f"cambiada{i} palabra", 1)
        h = procesa.dedup.hamming(procesa.dedup.simhash(base),
                                  procesa.dedup.simhash(copia))
        self.assertTrue(4 <= h <= 10, f"el par debe estar en la zona gris, hamming={h}")
        a = self._doc(body=base, fuente=1, dia="2026-08-20")
        b = self._doc(body=copia, fuente=1, dia="2026-08-20")
        res = self._ejecutar()
        self.assertIsNone(self._fila(a)["duplicate_of"])
        self.assertIsNone(self._fila(b)["duplicate_of"])
        self.assertEqual(res["contadores"]["near_dup"], 0)


class TestRepublicacionMinHash(Base):  # §10.12
    def test_inter_fuente_republicado(self):
        # Fechas RELATIVAS al reloj real (regla en equipo/MEJORAS.md): el
        # índice MinHash solo carga los últimos VENTANA_MINHASH_DIAS días desde
        # db.now_iso() (procesa.construir_indice); una fecha fija acaba FUERA
        # de la ventana y el test dependía del calendario (rompió 2026-09-18).
        base = texto_largo("rep", 120)
        ayer = (date.fromisoformat(db.now_iso()[:10])
                - timedelta(days=1)).isoformat()
        self._doc(body=base, fuente=1, dia=ayer, pub=f"{ayer}T10:00:00Z")
        eco = base + " cola distinta al final del texto republicado"
        b = self._doc(body=eco, fuente=2, dia=ayer, pub=f"{ayer}T10:00:00Z")
        res = self._ejecutar()
        f = self._fila(b)
        self.assertIsNotNone(f["duplicate_of"])
        self.assertEqual(res["contadores"]["republicados"], 1)

    def test_indice_actualizado_entre_lotes(self):  # rev. H3
        # Dos republicaciones FUERA de la ventana de 28 días (no entran en el
        # índice de arranque) en lotes distintos: la 2ª solo ve a la 1ª si el
        # índice se actualiza tras comitear cada lote.
        base = texto_largo("h3", 120)
        self._doc(body=base, fuente=1, dia="2026-05-01")
        b = self._doc(body=base, fuente=2, dia="2026-05-01")
        res = self._ejecutar(lote=1)
        self.assertIsNotNone(self._fila(b)["duplicate_of"])
        self.assertEqual(res["contadores"]["republicados"], 1)

    def test_doc_muy_corto_no_entra_en_indice(self):
        # <5 palabras: firma centinela J=1 consigo misma (rev. H6); jamás dup.
        a = self._doc(body="hola mundo", fuente=1, dia="2026-08-20")
        b = self._doc(body="hola mundo", fuente=2, dia="2026-08-20")
        res = self._ejecutar()
        self.assertIsNone(self._fila(a)["duplicate_of"])
        self.assertIsNone(self._fila(b)["duplicate_of"])
        self.assertEqual(res["contadores"]["republicados"], 0)


class TestEmoStats(Base):  # §10.14 · trampa 8
    def test_sin_pesos_no_hay_fila_nd_jamas_cero(self):
        # peso_fuente 0 → Σw²=0 → agregar_dia None → SIN fila (no 0.0); y en
        # re-cálculo la fila vieja se BORRA (DELETE antes del UPSERT, rev. H2).
        d = self._doc(body=TEXTO_EMO, dia="2026-08-20")
        self._ejecutar()
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM emo_stats WHERE day = '2026-08-20'").fetchone()[0], 1)
        with db.tx(self.con):
            self.con.execute("UPDATE sources SET peso = 0.0 WHERE id = 1")
        with mock.patch.object(procesa.bot_heur, "BOT_VERSION", "bot-2"):
            self._ejecutar()                       # recalcula el día
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM emo_stats WHERE day = '2026-08-20'").fetchone()[0], 0)

    def test_media_ponderada_con_peso_fuente(self):
        # w = calidad × documents.peso × sources.peso (D-CONS-1); f2 pesa 0.5
        a = self._doc(body=TEXTO_EMO, fuente=1, dia="2026-08-20")
        b = self._doc(body="la rabia y el miedo con tristeza y asco",
                      fuente=2, dia="2026-08-20")
        self._ejecutar()
        fila = self.con.execute(
            "SELECT valence_mean, arousal_mean, n, n_efectivo FROM emo_stats"
            " WHERE day = '2026-08-20' AND lang = 'es'").fetchone()
        self.assertIsNotNone(fila)
        self.assertEqual(fila["n"], 2)
        ca, cb = self._fila(a)["calidad_score"], self._fila(b)["calidad_score"]
        w1, w2 = ca * 1.0 * 1.0, cb * 1.0 * 0.5
        # v ya reescalada v'=2v−1: TEXTO_EMO → 0.7333; rabia/miedo/tristeza/asco → −0.8
        self.assertAlmostEqual(fila["valence_mean"],
                               (0.7333 * w1 + (-0.8) * w2) / (w1 + w2), places=3)
        esperado = (w1 + w2) ** 2 / (w1 ** 2 + w2 ** 2)
        self.assertAlmostEqual(fila["n_efectivo"], esperado, places=3)

    def test_emocion_de_dia_relee_docs_de_lotes_anteriores(self):  # trampa 7
        self._doc(body=TEXTO_EMO, dia="2026-08-20")
        self._ejecutar()
        n1 = self.con.execute("SELECT n FROM emo_stats WHERE day='2026-08-20'").fetchone()[0]
        self._doc(body=TEXTO_EMO, dia="2026-08-20")
        self._ejecutar()
        n2 = self.con.execute("SELECT n FROM emo_stats WHERE day='2026-08-20'").fetchone()[0]
        self.assertEqual((n1, n2), (1, 2))         # el día se recalcula desde BD

    def test_recalculo_degradado_conserva_emo_stats(self):  # rev. Hamilton N1
        # Día CON fila emo_stats; re-ejecución que toca ese día con léxicos
        # AUSENTES (modo degradado): la fila SOBREVIVE (sin gate, el DELETE la
        # borra y vector()=None no la repone → la mutación muere).
        self._doc(body=TEXTO_EMO, dia="2026-08-20")
        self._ejecutar()
        fila = self.con.execute(
            "SELECT * FROM emo_stats WHERE day = '2026-08-20'").fetchone()
        self.assertIsNotNone(fila)
        self._doc(body=texto_largo("nuevo"), dia="2026-08-20")
        res = self._ejecutar(lexicos=None)         # modo degradado
        self.assertEqual(res["contadores"]["modo_degradado"], 1)
        self.assertEqual([tuple(r) for r in self.con.execute(
            "SELECT * FROM emo_stats WHERE day = '2026-08-20'")],
            [tuple(fila)])


class TestHistorialAutorReciente(Base):  # rev. Hamilton M2 / Dijkstra M2
    def test_rafaga_ve_las_500_mas_recientes(self):
        # Autor hiperactivo: 500 posts antiguos espaciados + ráfaga reciente
        # de 20 en <1 h. El historial debe cargar las 500 MÁS RECIENTES: con
        # las 500 más antiguas (mutación) la ráfaga queda fuera y la flag
        # sería False.
        autor = "bot_hiperactivo"
        for i in range(500):               # antiguos, espaciados (sin ráfaga)
            self._doc(body=texto_largo(f"old{i}", 10), autor=autor,
                      pub=f"2020-{1 + i % 12:02d}-{1 + (i // 12) % 27:02d}"
                          f"T{(i * 7) % 24:02d}:{(i * 13) % 60:02d}:00Z",
                      dia="2020-01-02")
        for k in range(20):                # ráfaga reciente en <1 h
            self._doc(body=texto_largo(f"burst{k}", 10), autor=autor,
                      pub=f"2026-08-20T10:{k:02d}:00Z", dia="2026-08-20")
        d = self._doc(body=texto_largo("objetivo", 10), autor=autor,
                      pub="2026-08-20T10:30:00Z", dia="2026-08-20")
        self._ejecutar()
        flags = json.loads(self._fila(d)["bot_flags"])
        self.assertTrue(flags["rafaga"])


class TestTermsOrdenAlfabetico(Base):  # rev. Dijkstra M4
    TERMINOS = [f"termino{i:02d}x" for i in range(40)]  # ≥3 chars, no stopwords

    def _mapa_ids(self, orden):
        """BD nueva: 2 docs con los MISMOS términos nuevos en orden de
        documentos distinto; devuelve {texto: id}."""
        tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez orden "))
        ruta = tmp / "orden.db"
        db.init_db(ruta)
        con = db.connect(ruta)
        try:
            with db.tx(con):
                con.execute(
                    "INSERT INTO sources(nombre, tipo, peso) VALUES ('f1','rss',1.0)")
            cuerpos = [" ".join(self.TERMINOS[:20] * 2),
                       " ".join(self.TERMINOS[20:] * 2)]
            for n, cuerpo in enumerate([cuerpos[i] for i in orden], 1):
                with db.tx(con):
                    con.execute(
                        "INSERT INTO documents(source_id, url_hash, published_at,"
                        " published_at_real, fetched_at, body_text, content_hash, dia)"
                        " VALUES (1, ?, '2026-08-20T10:00:00Z', 1,"
                        " '2026-08-20T11:00:00Z', ?, ?, '2026-08-20')",
                        (f"u{n}", cuerpo, f"h{n}"))
            procesa.ejecutar(self.cfg, con, detector=self.det, lexicos=_lex())
            return dict(con.execute("SELECT text, id FROM terms").fetchall())
        finally:
            con.close()

    def test_mismos_ids_en_orden_de_documentos_distinto(self):
        # El alta de terms nuevos va EN ORDEN ALFABÉTICO (rev. H4): sin ese
        # sorted(), el orden lo manda la iteración del set y diverge entre
        # procesos/despliegues. Con 40 términos, que el orden del set coincida
        # con el alfabético por azar es despreciable: la mutación muere.
        orden_alta = []

        def espia(con, texto, tipo, cluster_key=None):
            if tipo == "term":
                orden_alta.append(texto)
            return real_alta(con, texto, tipo, cluster_key)

        real_alta = procesa._alta_term
        with mock.patch.object(procesa, "_alta_term", espia):
            mapa_ab = self._mapa_ids([0, 1])
        altas = [t for t in orden_alta if t in self.TERMINOS]
        self.assertEqual(sorted(set(altas)), sorted(self.TERMINOS))
        self.assertEqual(list(dict.fromkeys(altas)), sorted(self.TERMINOS))
        mapa_ba = self._mapa_ids([1, 0])
        self.assertEqual({t: mapa_ab[t] for t in self.TERMINOS},
                         {t: mapa_ba[t] for t in self.TERMINOS})


class TestConcurrencia(Base):  # §10.15 · C-B4-5
    def test_escritor_concurrente_sin_operational_error(self):
        for i in range(6):
            self._doc(body=texto_largo(f"c{i}"), dia="2026-08-20")
        errores = []
        parar = threading.Event()

        def escritor():
            # La conexión se crea EN el hilo (check_same_thread): busy_timeout
            # por conexión, como en producción (V7).
            otra = db.connect(self.db_path)
            n = 100
            try:
                while not parar.is_set():
                    try:
                        with db.tx(otra):
                            otra.execute(
                                "INSERT INTO documents(source_id, url_hash, body_text,"
                                " content_hash, dia, published_at_real) VALUES"
                                " (1, ?, '', ?, '2026-08-21', 0)", (f"w{n}", f"wh{n}"))
                            n += 1
                    except sqlite3.OperationalError as e:
                        errores.append(e)
                    except sqlite3.IntegrityError:
                        pass
            finally:
                otra.close()
        hilo = threading.Thread(target=escritor)
        hilo.start()
        res = self._ejecutar(lote=2)
        parar.set()
        hilo.join()
        self.assertEqual(errores, [])             # cero OperationalError (C-B4-5)
        c = res["contadores"]
        # sin pérdida: todo lo seleccionado se procesó (invariante) y cada doc
        # del escritor quedó pendiente para la siguiente ejecución
        self.assertEqual(c["procesados"] + c["errores"], res["pendientes"])
        self.assertGreaterEqual(res["pendientes"], 6)
        n_rest = self.con.execute(
            "SELECT COUNT(*) FROM documents WHERE calidad_score IS NULL").fetchone()[0]
        self.assertEqual(n_rest, self.con.execute(
            "SELECT COUNT(*) FROM documents").fetchone()[0] - res["pendientes"])


class TestDiaParcial(Base):  # §10.16 · D-B4-12
    def test_dia_por_debajo_de_la_mediana_se_registra(self):
        for d in range(1, 29):                     # 28 días medianos de 4 docs
            for i in range(4):
                self._doc(body=texto_largo(f"d{d}p{i}"), dia=f"2026-07-{d:02d}")
        self._doc(body=texto_largo("parcial"), dia="2026-07-29")  # 1 < 0.5×4
        res = self._ejecutar()
        self.assertIn("2026-07-29", res["dias_parciales"])
        n = self.con.execute(
            "SELECT COUNT(*) FROM ops_metrics WHERE clave = 'procesa.dia_parcial'"
            ).fetchone()[0]
        self.assertEqual(n, 1)


class TestGuardianCapa(Base):  # §10.18 · C-B4-6
    def test_sin_sqlite_connect_fuera_de_db(self):
        import re as _re
        raiz = Path(__file__).resolve().parent.parent / "sibila"
        for py in raiz.rglob("*.py"):
            if py.name in ("db.py", "informe_datos.py", "doctor.py"):
                continue  # ro-mode propio (D-B7)
            self.assertNotIn("sqlite3.connect", py.read_text(encoding="utf-8"),
                             f"{py.name} abre conexiones fuera de db.py")

    def test_procesa_sin_regex_nlp(self):
        src = (Path(__file__).resolve().parent.parent
               / "sibila" / "procesa.py").read_text(encoding="utf-8")
        self.assertNotIn("re.compile", src)


class TestOrIgnoreVigilante(Base):  # §10.19 · trampa 4
    def test_insert_ignorado_sin_fila_es_fallo_visible(self):
        class ConFalsa:
            def execute(self, sql, params=()):
                return self

            def fetchone(self):
                return None
        with self.assertRaises(procesa.ProcesaError):
            procesa._alta_term(ConFalsa(), "x", "term")


class TestOpsMetrics(Base):  # §10.21 · D-B4-10
    def test_las_10_claves_existen(self):
        self._doc(body=texto_largo("m"))
        self._ejecutar()
        claves = {r[0] for r in self.con.execute(
            "SELECT DISTINCT clave FROM ops_metrics WHERE clave LIKE 'procesa.%'")}
        self.assertEqual(claves, {f"procesa.{k}" for k in procesa.CLAVES_METRICAS})

    def test_hoy_datetime_se_normaliza(self):  # rev. Dijkstra M2 · D-047
        # El contrato admite date|str|datetime (corre inyecta D+1T06:00): sin
        # normalizar, el ts quedaba "2026-09-02 06:00:00+00:00T23:59:59Z".
        self._doc(dia="2026-09-01", pub="2026-09-01T10:00:00Z")
        self._ejecutar(hoy=datetime(2026, 9, 2, 6, 0, tzinfo=timezone.utc))
        tss = {r[0] for r in self.con.execute(
            "SELECT ts FROM ops_metrics WHERE clave LIKE 'procesa.%'")}
        self.assertEqual(tss, {"2026-09-02T23:59:59Z"})


class TestJsonFlags(Base):  # §10.22 · trampa 9
    def test_cuatro_claves_ordenadas_y_parseable(self):
        d = self._doc(body=texto_largo("j"))
        self._ejecutar()
        crudo = self._fila(d)["bot_flags"]
        self.assertEqual(crudo, json.dumps(json.loads(crudo), sort_keys=True))
        self.assertEqual(set(json.loads(crudo)),
                         {"marcador", "plantilla", "rafaga", "regularidad"})


class TestDocVenenoso(Base):  # D-B4-11 · invariante
    def test_doc_que_explota_se_cuenta_y_no_queda_pendiente(self):
        a = self._doc(body=texto_largo("ok"))
        b = self._doc(body=texto_largo("boom"))
        real = procesa.bot_heur.flags

        def rompe(ctx):
            if "boom" in ctx.texto_limpio:
                raise RuntimeError("veneno")
            return real(ctx)
        with mock.patch.object(procesa.bot_heur, "flags", rompe):
            res = self._ejecutar()
        c = res["contadores"]
        self.assertEqual((c["procesados"], c["errores"]), (1, 1))
        self.assertEqual(c["procesados"] + c["errores"], res["pendientes"])
        f = self._fila(b)
        self.assertEqual(f["calidad_score"], 0.0)  # procesado-y-excluido
        self.assertIsNone(f["lang"])
        self.assertEqual(self._ejecutar()["pendientes"], 0)  # no vuelve a salir


class TestDegradado(Base):  # D-B4-10
    def test_sin_detector_aviso_y_metrica(self):
        self._doc(body=texto_largo("deg"))
        res = self._ejecutar(detector=None, lexicos=None)
        self.assertEqual(res["contadores"]["modo_degradado"], 1)
        self.assertTrue(any("idioma" in a for a in res["avisos"]))
        self.assertTrue(any("léxicos" in a for a in res["avisos"]))
        self.assertEqual(res["contadores"]["sin_idioma"], 1)  # lang NULL → excluido
        n = self.con.execute(
            "SELECT COUNT(*) FROM ops_metrics WHERE clave='procesa.modo_degradado'"
            " AND valor = 1.0").fetchone()[0]
        self.assertEqual(n, 1)

    def test_humo_recursos_bajo_ruta_con_acentos(self):  # §10.20
        ruta = self.tmp / "recursos José Pérez"
        ruta.mkdir(exist_ok=True)
        for nombre, fix in (("nrc_vad_en.txt", "vad_en.txt"),
                            ("nrc_vad_es.txt", "vad_es.txt"),
                            ("nrc_emociones_en.txt", "emo_en.txt"),
                            ("nrc_emociones_es.txt", "emo_es.txt")):
            (ruta / nombre).write_bytes((FIX / fix).read_bytes())
        lex = cargar_lexicos({"nrc_vad_en": ruta / "nrc_vad_en.txt",
                              "nrc_vad_es": ruta / "nrc_vad_es.txt",
                              "nrc_emociones_en": ruta / "nrc_emociones_en.txt",
                              "nrc_emociones_es": ruta / "nrc_emociones_es.txt"},
                             verificar_sha=False)
        self.assertIsNotNone(lex)
        self.assertIsNone(procesa.idioma.cargar_detector(ruta / "lid.176.ftz"))


class TestRecomputable(Base):  # C-B4-9
    def test_borrar_stats_y_reprocesar_reconstruye_igual(self):
        for i in range(3):
            self._doc(body=texto_largo(f"rb{i}") + " " + TEXTO_EMO, dia="2026-08-20")
        self._ejecutar()
        ts = self.con.execute("SELECT * FROM term_stats ORDER BY day, term_id").fetchall()
        es = self.con.execute("SELECT * FROM emo_stats ORDER BY day, lang").fetchall()
        with db.tx(self.con):
            self.con.execute("DELETE FROM term_stats WHERE day = '2026-08-20'")
            self.con.execute("DELETE FROM emo_stats WHERE day = '2026-08-20'")
        self._ejecutar(todo=True, dia="2026-08-20")
        self.assertEqual([tuple(r) for r in ts],
                         [tuple(r) for r in self.con.execute(
                             "SELECT * FROM term_stats ORDER BY day, term_id")])
        self.assertEqual([tuple(r) for r in es],
                         [tuple(r) for r in self.con.execute(
                             "SELECT * FROM emo_stats ORDER BY day, lang")])


if __name__ == "__main__":
    unittest.main()

"""T1 · db.py y schema.sql (17 tests, plan Liskov §2.6).
Toda la suite corre bajo un directorio con ESPACIO y ACENTOS (trampa T3 global).
DB siempre en archivo real (nunca :memory:: WAL devuelve 'memory' ahí — verificado)."""
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sibila import db


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))

    def setUp(self):
        self.db_path = self.tmp / f"test_{self._testMethodName}.db"
        db.init_db(self.db_path)
        self.con = db.connect(self.db_path)
        self.addCleanup(self.con.close)

    def _term(self, text="crisis"):
        with db.tx(self.con):
            cur = self.con.execute("INSERT INTO terms(text, type) VALUES (?, 'term')", (text,))
        return cur.lastrowid

    def _doc(self, url_hash="u1"):
        with db.tx(self.con):
            cur = self.con.execute("INSERT INTO documents(url_hash) VALUES (?)", (url_hash,))
        return cur.lastrowid

    def _signal(self, tid, day="2026-01-05", metric="z_r", status="nuevo", target_type="term"):
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO signals(day, target_type, target_id, metric, score, status, created_at)"
                " VALUES (?, ?, ?, ?, 3.5, ?, '2026-01-05T00:00:00Z')",
                (day, target_type, tid, metric, status))


class TestInitDb(Base):
    def test_init_crea_db_y_version(self):
        self.assertTrue(self.db_path.exists())
        con = db.connect(self.db_path)
        self.addCleanup(con.close)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_init_idempotente(self):
        with db.tx(self.con):
            self.con.execute("INSERT INTO sources(nombre) VALUES ('lobsters')")
        db.init_db(self.db_path)  # segundo init: no-op, JAMÁS destructivo
        n = self.con.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        self.assertEqual(n, 1)

    def test_init_rechaza_version_futura(self):
        self.con.execute("PRAGMA user_version = 99")
        with self.assertRaises(db.SchemaError):
            db.init_db(self.db_path)
        # y NO tocó la versión
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone()[0], 99)


class TestPragmas(Base):
    def test_pragmas_activos(self):
        self.assertTrue(self.con.execute("PRAGMA journal_mode").fetchone()[0].startswith("wal"))
        self.assertEqual(self.con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.con.execute("PRAGMA busy_timeout").fetchone()[0], 30000)

    def test_foreign_keys_activas_de_verdad(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with db.tx(self.con):
                self.con.execute("INSERT INTO documents(source_id, url_hash) VALUES (999, 'huerfano')")


class TestSchema(Base):
    def test_verify_schema_limpio(self):
        self.assertEqual(db.verify_schema(self.con), [])

    def test_verify_schema_detecta_tabla_borrada(self):
        self.con.execute("DROP TABLE ops_metrics")
        problemas = db.verify_schema(self.con)
        self.assertTrue(any("ops_metrics" in p for p in problemas), problemas)

    def test_tablas_completas(self):
        tablas = {f[0] for f in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        self.assertEqual(tablas, {"sources", "documents", "terms", "term_stats", "emo_stats",
                                  "signals", "predictions", "echo_flags", "alert_log",
                                  "gdelt_ref", "ops_metrics", "conector_cursor"})

    def test_columnas_clave_documents(self):
        cols = {f[1]: f[2].upper() for f in self.con.execute("PRAGMA table_info(documents)")}
        for nombre, tipo in [("simhash", "TEXT"), ("published_at", "TEXT"),
                             ("published_at_real", "INTEGER"), ("bot_flags", "TEXT"),
                             ("bot_detector_version", "TEXT"), ("author_hash", "TEXT"),
                             ("peso", "REAL"), ("dia", "TEXT")]:
            self.assertIn(nombre, cols)
            self.assertEqual(cols[nombre], tipo, nombre)
        self.assertEqual(cols["simhash"], "TEXT")  # NUNCA INTEGER (trampa T1, int64)

    def test_status_inmaduro_admitido(self):
        self._signal(self._term(), status="inmaduro")  # no lanza
        n = self.con.execute("SELECT COUNT(*) FROM signals WHERE status='inmaduro'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_dominios_rechazan_basura(self):
        tid = self._term()
        doc = self._doc()
        casos = [
            ("signals.status='maduro'",
             "INSERT INTO signals(day,target_type,target_id,metric,status) VALUES ('2026-01-05','term',%d,'z_r','maduro')" % tid),
            ("target_type='hashtag'",
             "INSERT INTO signals(day,target_type,target_id,metric,status) VALUES ('2026-01-05','hashtag',%d,'z_r','nuevo')" % tid),
            ("metric='t_test'",
             "INSERT INTO signals(day,target_type,target_id,metric,status) VALUES ('2026-01-05','term',%d,'t_test','nuevo')" % tid),
            ("sources.stratum='vip'", "INSERT INTO sources(nombre,stratum) VALUES ('x','vip')"),
            ("terms.type='emoji'", "INSERT INTO terms(text,type) VALUES ('e','emoji')"),
            ("echo_flags.tipo='spam'",
             "INSERT INTO echo_flags(doc_id,tipo,score) VALUES (%d,'spam',0.5)" % doc),
            ("echo_flags.score=1.5",
             "INSERT INTO echo_flags(doc_id,tipo,score) VALUES (%d,'meme',1.5)" % doc),
            ("predictions.estado='dudosa'", "INSERT INTO predictions(estado) VALUES ('dudosa')"),
            ("predictions.madura=2", "INSERT INTO predictions(madura) VALUES (2)"),
            ("documents.published_at_real=2", "INSERT INTO documents(url_hash,published_at_real) VALUES ('z',2)"),
        ]
        for nombre, sql in casos:
            with self.subTest(caso=nombre):
                with self.assertRaises(sqlite3.IntegrityError, msg=nombre):
                    with db.tx(self.con):
                        self.con.execute(sql)

    def test_invariante_fecha_real(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with db.tx(self.con):
                self.con.execute(
                    "INSERT INTO documents(url_hash, published_at, published_at_real)"
                    " VALUES ('f1', '2026-01-01T00:00:00Z', 0)")
        with db.tx(self.con):  # fecha desconocida: NULL + 0 → válido (spec §5)
            self.con.execute(
                "INSERT INTO documents(url_hash, published_at, published_at_real) VALUES ('f2', NULL, 0)")

    def test_simhash_text_hex(self):
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO documents(url_hash, simhash) VALUES ('s1', 'a554f1f06d019f4e')")
        leido = self.con.execute("SELECT simhash FROM documents WHERE url_hash='s1'").fetchone()[0]
        self.assertEqual(leido, "a554f1f06d019f4e")  # el hex del vector (e), ≥2⁶³, como TEXTO idéntico
        self.assertIsInstance(leido, str)
        for malo in ("A554F1F06D019F4E", "xyz"):
            with self.subTest(malo=malo):
                with self.assertRaises(sqlite3.IntegrityError):
                    with db.tx(self.con):
                        self.con.execute(
                            "INSERT INTO documents(url_hash, simhash) VALUES (?, ?)", ("s2" + malo[:1], malo))

    def test_uniques_activos(self):
        tid = self._term()
        self._signal(tid)
        with self.assertRaises(sqlite3.IntegrityError):
            self._signal(tid)  # duplica (day,target_type,target_id,metric)
        with db.tx(self.con):
            self.con.execute("INSERT INTO term_stats(day, term_id, docs) VALUES ('2026-01-05', ?, 3)", (tid,))
        with self.assertRaises(sqlite3.IntegrityError):
            with db.tx(self.con):
                self.con.execute("INSERT INTO term_stats(day, term_id, docs) VALUES ('2026-01-05', ?, 9)", (tid,))
        doc = self._doc()
        with db.tx(self.con):
            self.con.execute("INSERT INTO echo_flags(doc_id, tipo, score) VALUES (?, 'meme', 0.5)", (doc,))
        with self.assertRaises(sqlite3.IntegrityError):
            with db.tx(self.con):
                self.con.execute("INSERT INTO echo_flags(doc_id, tipo, score) VALUES (?, 'meme', 0.7)", (doc,))
        with db.tx(self.con):
            self.con.execute("INSERT INTO gdelt_ref(tema, day, n) VALUES ('crisis', '2026-01-05', 25)")
        with self.assertRaises(sqlite3.IntegrityError):
            with db.tx(self.con):
                self.con.execute("INSERT INTO gdelt_ref(tema, day, n) VALUES ('crisis', '2026-01-05', 30)")
        with self.assertRaises(sqlite3.IntegrityError):
            self._term()  # text UNIQUE
        with self.assertRaises(sqlite3.IntegrityError):
            self._doc()  # url_hash UNIQUE
        with db.tx(self.con):
            self.con.execute("INSERT INTO sources(nombre) VALUES ('dup')")
        with self.assertRaises(sqlite3.IntegrityError):  # sources.nombre UNIQUE (rev. M2, cerrojo doble)
            with db.tx(self.con):
                self.con.execute("INSERT INTO sources(nombre) VALUES ('dup')")

    def test_dia_forma(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with db.tx(self.con):
                self.con.execute("INSERT INTO documents(url_hash, dia) VALUES ('d1', '2026/01/05')")
        with db.tx(self.con):
            self.con.execute("INSERT INTO documents(url_hash, dia) VALUES ('d2', '2026-01-05')")


class TestTx(Base):
    def test_tx_commit_y_rollback(self):
        with db.tx(self.con):
            self.con.execute("INSERT INTO terms(text, type) VALUES ('commit_ok', 'term')")
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM terms WHERE text='commit_ok'").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            with db.tx(self.con):
                self.con.execute("INSERT INTO terms(text, type) VALUES ('rollback', 'term')")
                raise ValueError("provocado")
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM terms WHERE text='rollback'").fetchone()[0], 0)
        with self.assertRaises(RuntimeError):
            with db.tx(self.con):
                with db.tx(self.con):
                    pass

    def test_now_iso_formato(self):
        self.assertRegex(db.now_iso(), re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"))


class TestRegresiones(Base):
    """Regresiones de la revisión del bloque 1 (Dijkstra B2/M2/M3)."""

    def test_dia_forma_rechazada_en_series(self):  # rev. M2: el GLOB R3 muerde en TODAS las series
        tid = self._term()
        casos = [
            ("term_stats", "INSERT INTO term_stats(day, term_id, docs) VALUES ('2026/01/05', %d, 3)" % tid),
            ("emo_stats", "INSERT INTO emo_stats(day, lang) VALUES ('2026/01/05', 'es')"),
            ("signals", "INSERT INTO signals(day, target_type, target_id, metric, status)"
                        " VALUES ('2026/01/05', 'term', %d, 'z_r', 'nuevo')" % tid),
            ("gdelt_ref", "INSERT INTO gdelt_ref(tema, day, n) VALUES ('x', '2026/01/05', 5)"),
        ]
        for tabla, sql in casos:
            with self.subTest(tabla=tabla):
                with self.assertRaises(sqlite3.IntegrityError):
                    with db.tx(self.con):
                        self.con.execute(sql)

    def test_tx_keyboardinterrupt_no_envenena(self):  # rev. B2
        with self.assertRaises(KeyboardInterrupt):
            with db.tx(self.con):
                self.con.execute("INSERT INTO terms(text, type) VALUES ('ki', 'term')")
                raise KeyboardInterrupt
        self.assertFalse(self.con.in_transaction)  # conexión NO envenenada
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM terms WHERE text='ki'").fetchone()[0], 0)
        with db.tx(self.con):  # la siguiente tx funciona
            self.con.execute("INSERT INTO terms(text, type) VALUES ('despues', 'term')")

    def test_init_base_malformada_schemaerror(self):  # rev. M3: diagnóstico en español, no OperationalError cruda
        ruta = self.tmp / "malformada.db"
        con = sqlite3.connect(str(ruta))
        con.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, cosa TEXT)")  # tabla a medias, v0
        con.commit()
        con.close()
        with self.assertRaises(db.SchemaError) as ctx:
            db.init_db(ruta)
        self.assertIn("no es conforme", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

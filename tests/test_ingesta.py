"""T1 · ingesta.py: validación del contrato (frontera duck-typing, D-B2-07),
normalización y hashes (vectores congelados del plan), persistencia, dedup
determinista, dia (D-B2-04), ops_metrics (D-B2-06), cursor y HMAC (plan Liskov §6)."""
import hashlib
import hmac as hmac_mod
import sqlite3
import threading
import unittest
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import MappingProxyType

from sibila import db, ingesta
from sibila.config import Config
from sibila.ingesta import (IngestaError, es_fecha_valida, hash_documento, hash_url,
                            normalizar_url, validar_rawdoc)

UTC = timezone.utc
RAIZ = Path(__file__).resolve().parent.parent


class FakeConector:
    """Conector de mentira: devuelve una lista fija y un cursor nuevo; registra lo recibido."""

    def __init__(self, docs, cursor_nuevo='{"vistos":[]}', nombre="reddit"):
        self._docs = docs
        self._cursor_nuevo = cursor_nuevo
        self.nombre = nombre
        self.cfg = {}
        self.recibido = None

    def fetch(self, cfg, cursor, **kw):
        self.recibido = cursor
        return list(self._docs), self._cursor_nuevo


class FakeDoc:
    def __init__(self, fuente="reddit", url="https://e.com/1", author_raw="nora",
                 published_at=None, body="texto de prueba", crudo="crudo", lang=None):
        self.fuente, self.url, self.author_raw = fuente, url, author_raw
        self.published_at, self.body, self.crudo, self.lang = published_at, body, crudo, lang


def cfg_con(clave=None):
    return Config(data_dir=Path("/tmp"), db_path=Path("/tmp/x.db"), log_level="INFO",
                  secretos=MappingProxyType({"hmac_key": clave} if clave else {}), avisos=())


# ------------------------------------------------------------- contrato RawDoc

class TestContratoRawDoc(unittest.TestCase):
    def test_validos(self):
        self.assertEqual(validar_rawdoc(FakeDoc()), [])
        self.assertEqual(validar_rawdoc(FakeDoc(body="")), [])          # "" solo con url
        self.assertEqual(validar_rawdoc(FakeDoc(url=None, body="x")), [])
        self.assertEqual(validar_rawdoc(FakeDoc(published_at=None, author_raw=None)), [])
        self.assertEqual(validar_rawdoc(FakeDoc(url="HTTP://E.COM/1")), [])  # rev. M12

    def test_invalidos(self):
        casos = [
            ("fecha naive", FakeDoc(published_at=datetime(2026, 7, 20, 10))),
            ("fecha no-UTC", FakeDoc(published_at=datetime(
                2026, 7, 20, 10, tzinfo=timezone(timedelta(hours=2))))),
            ("año 1999", FakeDoc(published_at=datetime(1999, 1, 1, tzinfo=UTC))),
            ("url ftp", FakeDoc(url="ftp://e.com/1")),
            ("sin url y sin cuerpo", FakeDoc(url=None, body="")),
            ("crudo vacío", FakeDoc(crudo="")),
            ("fuente vacía", FakeDoc(fuente="")),
            ("body no texto", FakeDoc(body=123)),
            ("autor no texto", FakeDoc(author_raw=42)),
        ]
        for nombre, d in casos:
            with self.subTest(caso=nombre):
                self.assertNotEqual(validar_rawdoc(d), [], nombre)

    def test_es_fecha_valida(self):
        self.assertTrue(es_fecha_valida(datetime(2026, 1, 1, tzinfo=UTC)))
        self.assertFalse(es_fecha_valida(None))
        self.assertFalse(es_fecha_valida(datetime(2026, 1, 1)))
        self.assertFalse(es_fecha_valida(datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))))
        self.assertFalse(es_fecha_valida(datetime(1999, 1, 1, tzinfo=UTC)))


class TestNormalizacionYHashes(unittest.TestCase):
    def test_vectores_url(self):  # congelados en el plan Liskov §7
        self.assertEqual(
            normalizar_url("HTTP://Example.COM/a/?utm_source=r&b=2&a=1#f"),
            "http://example.com/a?a=1&b=2")
        self.assertEqual(normalizar_url("https://example.com"),
                         normalizar_url("https://example.com/"))
        self.assertEqual(normalizar_url("https://example.com:443/x"),
                         "https://example.com/x")
        self.assertEqual(normalizar_url("http://example.com:80/x"), "http://example.com/x")
        self.assertEqual(normalizar_url("https://example.com/x?fbclid=1&gclid=2"),
                         "https://example.com/x")
        u = "HTTPS://Example.COM/a/b/?utm_source=x&b=2&a=1#frag"
        self.assertEqual(normalizar_url(normalizar_url(u)), normalizar_url(u))  # idempotente

    def test_url_no_http_valueerror(self):
        for mala in ("ftp://e.com/1", "https://", "no-es-url"):
            with self.subTest(url=mala):
                with self.assertRaises(ValueError):
                    normalizar_url(mala)

    def test_hashes_espacios_separados(self):
        self.assertNotEqual(hash_url("https://e.com/1"), hash_documento("f", "https://e.com/1"))
        self.assertEqual(len(hash_url("u")), 64)
        self.assertEqual(hash_url("u"), hash_url("u"))  # determinista

    def test_vector_content_hash_congelado(self):
        """D-B2-03 (rev. Dijkstra M6): NFC + colapso de espacios, SIN minúsculas.
        'El   rápido\\n\\tzorro   salta' (y su forma NFD) → d3a1fbdf…07b7."""
        self.assertEqual(ingesta._norm_texto("El   rápido\n\tzorro   salta"),
                         "El rápido zorro salta")
        self.assertEqual(
            hashlib.sha256(ingesta._norm_texto("El   rápido\n\tzorro   salta")
                           .encode("utf-8")).hexdigest(),
            "d3a1fbdf22b0ef093b4499240ae962ef92781132c5ab61898d2dfb3bc3b407b7")
        nfd = unicodedata.normalize("NFD", "El   rápido\n\tzorro   salta")
        self.assertEqual(ingesta._norm_texto(nfd), "El rápido zorro salta")  # NFC≠NFD cazado
        # sin minúsculas: 'Texto CON Espacios' NO se pliega
        self.assertEqual(ingesta._norm_texto("  Texto   CON    Espacios "),
                         "Texto CON Espacios")


# ------------------------------------------------------------- persistencia

class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))

    def setUp(self):
        self.db_path = self.tmp / f"test_{self._testMethodName}.db"
        db.init_db(self.db_path)
        self.con = db.connect(self.db_path)
        self.addCleanup(self.con.close)
        ingesta.asegurar_fuentes(self.con)

    def _corre(self, docs, cfg=None, nombre="reddit", cursor_nuevo='{"vistos":[]}',
               limite=None):
        c = FakeConector(docs, cursor_nuevo, nombre)
        res = ingesta.ingestar(cfg or cfg_con(), c, None, self.con, limite=limite)
        return res, c


class TestPersistencia(Base):
    def test_inserta_campos(self):
        fecha = datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC)
        res, _ = self._corre([FakeDoc(published_at=fecha, lang="es")])
        self.assertEqual(res["nuevos"], 1)
        fila = self.con.execute("SELECT * FROM documents").fetchone()
        src = self.con.execute("SELECT nombre FROM sources WHERE id = ?", (fila["source_id"],)).fetchone()
        self.assertEqual(src[0], "reddit")
        self.assertEqual(fila["published_at"], "2026-07-20T10:00:00Z")
        self.assertEqual(fila["published_at_real"], 1)
        self.assertEqual(fila["dia"], "2026-07-20")  # D-B2-04 (rev. B1 de ambos)
        self.assertRegex(fila["fetched_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(fila["body_text"], "texto de prueba")
        self.assertEqual(fila["lang"], "es")
        self.assertIsNotNone(fila["content_hash"])
        self.assertIsNone(fila["simhash"])
        self.assertIsNone(fila["duplicate_of"])
        self.assertEqual(fila["peso"], 1.0)

    def test_dia_es_la_fecha_utc_del_doc_no_la_de_ingesta(self):
        # doc publicado a las 23:30 UTC de ayer: dia = ayer, aunque se ingiere hoy
        fecha = datetime(2026, 7, 19, 23, 30, tzinfo=UTC)
        self._corre([FakeDoc(published_at=fecha)])
        self.assertEqual(self.con.execute("SELECT dia FROM documents").fetchone()[0],
                         "2026-07-19")

    def test_fecha_none_invariante(self):  # TP-N11 base: exclusión ESTRUCTURAL de baselines
        self._corre([FakeDoc()])
        fila = self.con.execute(
            "SELECT published_at, published_at_real, dia FROM documents").fetchone()
        self.assertIsNone(fila["published_at"])
        self.assertEqual(fila["published_at_real"], 0)
        self.assertIsNone(fila["dia"])

    def test_body_original_y_hash_normalizado(self):
        self._corre([FakeDoc(body="  Texto   CON    Espacios ")])
        fila = self.con.execute("SELECT body_text, content_hash FROM documents").fetchone()
        self.assertEqual(fila["body_text"], "  Texto   CON    Espacios ")  # original intacto
        esperado = hashlib.sha256("Texto CON Espacios".encode("utf-8")).hexdigest()
        self.assertEqual(fila["content_hash"], esperado)  # hash sobre NFC+colapso, SIN pliegue

    def test_body_vacio_content_hash_null_sin_falso_dup(self):
        res, _ = self._corre([FakeDoc(url="https://e.com/1", body=""),
                              FakeDoc(url="https://e.com/2", body="")])
        self.assertEqual(res["nuevos"], 2)  # body "" NUNCA deduplica
        nulos = self.con.execute(
            "SELECT COUNT(*) FROM documents WHERE content_hash IS NULL").fetchone()[0]
        self.assertEqual(nulos, 2)

    def test_ops_metrics_cuatro_claves(self):  # D-B2-06 (rev. Hamilton M11)
        self._corre([FakeDoc(url="https://e.com/1", body="uno"),
                     FakeDoc(url="https://e.com/1", body="dos"),
                     FakeDoc(published_at=datetime(2026, 7, 20, 10))])  # naive → error
        filas = dict(self.con.execute(
            "SELECT clave, valor FROM ops_metrics").fetchall())
        self.assertEqual(filas.get("ingesta.nuevos.reddit"), 1.0)
        self.assertEqual(filas.get("ingesta.duplicados_url.reddit"), 1.0)
        self.assertEqual(filas.get("ingesta.duplicados_contenido.reddit"), 0.0)
        self.assertEqual(filas.get("ingesta.errores.reddit"), 1.0)
        ts = self.con.execute("SELECT ts FROM ops_metrics LIMIT 1").fetchone()[0]
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_limite_recorta_en_modo_bd(self):  # rev. Dijkstra M2 / Hamilton M9
        docs = [FakeDoc(url=f"https://e.com/{i}", body=f"cuerpo {i}") for i in range(3)]
        res, _ = self._corre(docs, limite=1)
        self.assertEqual((res["recibidos"], res["nuevos"]), (1, 1))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 1)

    def test_limite_no_mueve_el_cursor(self):  # rev. Hamilton N1 ronda 2
        """Con limite activo el cursor NO se guarda: si se guardara, los documentos
        no procesados quedarían marcados como vistos y se perderían PARA SIEMPRE."""
        docs = [FakeDoc(url=f"https://e.com/{i}", body=f"cuerpo {i}") for i in range(3)]
        res, _ = self._corre(docs, limite=1, cursor_nuevo='{"vistos":["TODO"]}')
        self.assertEqual(res["nuevos"], 1)
        self.assertIsNone(ingesta.leer_cursor(self.con, "reddit"))  # cursor intacto
        self.assertIsNone(res["cursor"])  # el resultado refleja que no se movió
        # segunda pasada SIN límite: los 2 restantes llegan (nada se perdió)
        res2, _ = self._corre(docs, limite=None)
        self.assertEqual((res2["nuevos"], res2["dup_url"]), (2, 1))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 3)


class TestDedup(Base):
    def test_dedup_url(self):
        res, _ = self._corre([FakeDoc(url="https://e.com/1", body="uno"),
                              FakeDoc(url="https://e.com/1", body="dos")])
        self.assertEqual((res["nuevos"], res["dup_url"], res["dup_cont"]), (1, 1, 0))

    def test_dedup_contenido(self):
        res, _ = self._corre([FakeDoc(url="https://e.com/1", body="mismo"),
                              FakeDoc(url="https://e.com/2", body="mismo")])
        self.assertEqual((res["nuevos"], res["dup_url"], res["dup_cont"]), (1, 0, 1))

    def test_dedup_contenido_entre_lotes(self):
        self._corre([FakeDoc(url="https://e.com/1", body="mismo")])
        res2, _ = self._corre([FakeDoc(url="https://e.com/2", body="mismo")])
        self.assertEqual((res2["nuevos"], res2["dup_cont"]), (0, 1))

    def test_prioridad_url_sobre_contenido(self):  # determinista: primero url (T-B2-05)
        res, _ = self._corre([FakeDoc(url="https://e.com/1", body="A"),
                              FakeDoc(url="https://e.com/2", body="A"),   # dup_cont
                              FakeDoc(url="https://e.com/1", body="A")])  # choca con ambas: url gana
        self.assertEqual((res["nuevos"], res["dup_url"], res["dup_cont"]), (1, 1, 1))

    def test_utm_y_fragment_deduplican(self):
        res, _ = self._corre([FakeDoc(url="https://e.com/1?utm_source=x#f"),
                              FakeDoc(url="https://e.com/1")])
        self.assertEqual(res["dup_url"], 1)
        fila = self.con.execute("SELECT url_hash FROM documents").fetchone()
        self.assertEqual(fila["url_hash"], hash_url(normalizar_url("https://e.com/1")))

    def test_doc_sin_url_hash_alternativo(self):
        res, _ = self._corre([FakeDoc(url=None, crudo="abc"),
                              FakeDoc(url=None, crudo="abc")])
        self.assertEqual(res["dup_url"], 1)
        fila = self.con.execute("SELECT url_hash FROM documents").fetchone()
        self.assertEqual(fila["url_hash"], hash_documento("reddit", "abc"))

    def test_idempotente_segunda_pasada(self):  # base de TP-N8
        docs = [FakeDoc(url="https://e.com/1", body="cuerpo uno"),
                FakeDoc(url="https://e.com/2", body="cuerpo dos")]  # cuerpos DISTINTOS
        res1, _ = self._corre(docs)
        res2, _ = self._corre(docs)
        self.assertEqual(res1["nuevos"], 2)
        self.assertEqual(res2["nuevos"], 0)
        self.assertEqual(res2["dup_url"], 2)


class TestHmac(Base):
    def test_vector_literal_congelado(self):  # plan Liskov §4/§6.6 (rev. Hamilton M3)
        cfg = cfg_con("clave-de-prueba-bloque2")
        self._corre([FakeDoc(author_raw="alice")], cfg=cfg)
        fila = self.con.execute("SELECT author_hash FROM documents").fetchone()
        self.assertEqual(fila["author_hash"],
                         "0f39859bbf903dfbdd004efc4efcf79223dc559bac903d34e59044b016e7d226")

    def test_estable_entre_pasadas_y_sin_fuga(self):
        cfg = cfg_con("CLAVE-DE-PRUEBA")
        self._corre([FakeDoc(url="https://e.com/1", author_raw="nora", body="uno")], cfg=cfg)
        self._corre([FakeDoc(url="https://e.com/2", author_raw="nora", body="dos")], cfg=cfg)
        filas = self.con.execute(
            "SELECT author_hash FROM documents ORDER BY id").fetchall()
        self.assertEqual(filas[0][0], filas[1][0])  # mismo autor, mismo hash
        esperado = hmac_mod.new(b"CLAVE-DE-PRUEBA", "nora".encode(), hashlib.sha256).hexdigest()
        self.assertEqual(filas[0][0], esperado)  # strip + NFC, SIN minúsculas (plan §4)
        self.assertRegex(filas[0][0], r"^[0-9a-f]{64}$")
        for fila in self.con.execute("SELECT * FROM documents"):
            self.assertNotIn("nora", str(dict(fila)))  # la identidad NUNCA en claro

    def test_nfc_no_minusculas(self):  # rev. Dijkstra M5
        cfg = cfg_con("CLAVE")
        self._corre([FakeDoc(url="https://e.com/1", author_raw="José", body="a"),
                     FakeDoc(url="https://e.com/2",
                             author_raw=unicodedata.normalize("NFD", "José"), body="b"),
                     FakeDoc(url="https://e.com/3", author_raw="josé", body="c")], cfg=cfg)
        filas = [f[0] for f in self.con.execute(
            "SELECT author_hash FROM documents ORDER BY id").fetchall()]
        self.assertEqual(filas[0], filas[1])   # NFC == NFD (misma persona)
        self.assertNotEqual(filas[0], filas[2])  # 'José' != 'josé' (SIN pliegue: conservador)

    def test_sin_clave_null_y_sin_autor_null(self):
        self._corre([FakeDoc(author_raw="nora")], cfg=cfg_con(None))
        self._corre([FakeDoc(url="https://e.com/2", author_raw=None, body="otro cuerpo")],
                    cfg=cfg_con("CLAVE"))
        filas = self.con.execute("SELECT author_hash FROM documents ORDER BY id").fetchall()
        self.assertIsNone(filas[0][0])
        self.assertIsNone(filas[1][0])


class TestCursor(Base):
    def test_persiste_y_reanuda(self):
        self._corre([FakeDoc()], cursor_nuevo='{"vistos":["a"]}')
        guardado = ingesta.leer_cursor(self.con, "reddit")
        self.assertEqual(guardado, '{"vistos":["a"]}')
        c2 = FakeConector([], '{"vistos":["a","b"]}')
        ingesta.ingestar(cfg_con(), c2, guardado, self.con)
        self.assertEqual(c2.recibido, '{"vistos":["a"]}')  # reanudación exacta
        self.assertEqual(ingesta.leer_cursor(self.con, "reddit"), '{"vistos":["a","b"]}')


class TestErrores(Base):
    def test_doc_invalido_saltado_y_contado(self):
        malo = FakeDoc(published_at=datetime(2026, 7, 20, 10))  # naive: inválido
        res, _ = self._corre([malo, FakeDoc(url="https://e.com/9")])
        self.assertEqual((res["errores"], res["nuevos"]), (1, 1))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 1)

    def test_url_venenosa_no_veta_el_lote(self):  # rev. Dijkstra B2
        """Puerto fuera de rango / IPv6 rota: ValueError en urlsplit/.port. Antes ocurría
        DENTRO de la tx → rollback: 1 doc venenoso perdía el lote entero. Ahora la
        normalización es fase-CPU fuera de tx y el doc se cuenta como error."""
        venenosos = [FakeDoc(url="http://e.com:99999/x"),
                     FakeDoc(url="http://[::1/x")]
        buenos = [FakeDoc(url=f"https://e.com/{i}", body=f"ok {i}") for i in range(5)]
        res, _ = self._corre(venenosos + buenos)
        self.assertEqual((res["errores"], res["nuevos"]), (2, 5))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 5)

    def test_fetch_falla_nada_persiste(self):
        class Roto(FakeConector):
            def fetch(self, cfg, cursor, **kw):
                raise RuntimeError("fuente caída")
        with self.assertRaises(RuntimeError):
            ingesta.ingestar(cfg_con(), Roto([]), None, self.con)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
        self.assertIsNone(ingesta.leer_cursor(self.con, "reddit"))  # cursor intacto

    def test_restriccion_inesperada_es_ingestaerror_y_rollback(self):
        """rev. Hamilton M7/M5: INSERT OR IGNORE también silencia CHECK/FK (verificado en
        el plan §9.1). Si rowcount==0 sin dup url ni contenido → IngestaError VISIBLE y
        rollback atómico del lote (docs + cursor + métricas), no un dup fantasma."""
        self.con.execute(
            "CREATE TRIGGER sabotaje BEFORE INSERT ON documents BEGIN"
            " SELECT RAISE(IGNORE); END;")
        self.con.commit()
        with self.assertRaises(IngestaError):
            self._corre([FakeDoc(url="https://e.com/1", body="uno")])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
        self.assertIsNone(ingesta.leer_cursor(self.con, "reddit"))       # cursor intacto
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM ops_metrics WHERE clave LIKE 'ingesta.%'").fetchone()[0], 0)
        # y la fuente se recupera al quitar el sabotaje (el fallo no envenena nada)
        self.con.execute("DROP TRIGGER sabotaje")
        self.con.commit()
        res, _ = self._corre([FakeDoc(url="https://e.com/1", body="uno")])
        self.assertEqual(res["nuevos"], 1)


class TestCursorAtomico(Base):
    def test_cursor_roto_rollback_conjunto(self):  # Liskov #14 (rev. Dijkstra N3 r2)
        """Si guardar el cursor FALLA, los documentos del lote se revierten con él:
        cursor y datos juntos o nada (D-B2-03). Cursor de tipo no-str → la BD lo rechaza."""
        class CursorRoto(FakeConector):
            def fetch(self, cfg, cursor, **kw):
                return list(self._docs), {"vistos": []}  # dict, no str: inválido
        with self.assertRaises(Exception):
            ingesta.ingestar(cfg_con(), CursorRoto([FakeDoc()]), None, self.con)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
        self.assertIsNone(ingesta.leer_cursor(self.con, "reddit"))
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM ops_metrics WHERE clave LIKE 'ingesta.%'").fetchone()[0], 0)


class TestConcurrencia(Base):
    def test_dos_fuentes_en_paralelo(self):  # base de TP-N10
        docs_a = [FakeDoc(url=f"https://a.com/{i}", body=f"cuerpo a {i}") for i in range(20)]
        docs_b = [FakeDoc(fuente="lobsters", url=f"https://b.com/{i}", body=f"cuerpo b {i}")
                  for i in range(20)]
        errores = []

        def corre(docs, nombre):
            try:
                con = db.connect(self.db_path)
                ingesta.ingestar(cfg_con(), FakeConector(docs, nombre=nombre), None, con)
                con.close()
            except Exception as e:
                errores.append(e)

        hilos = [threading.Thread(target=corre, args=(docs_a, "reddit")),
                 threading.Thread(target=corre, args=(docs_b, "lobsters"))]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(errores, [])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 40)


class TestCliIngesta(unittest.TestCase):
    """Extremo a extremo por subprocess (plan Hopper §7): --sin-db, persistencia real,
    exit 2, aislamiento por fuente, avisos y resumen total.
    Sin PYTHONNOUSERSITE: las deps del bloque 2 viven en user-site del entorno (como en Hermes)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        cls.fixture_vacio = cls.tmp / "vacio.xml"
        cls.fixture_vacio.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0"><channel><title>vacío</title>'
            '<link>https://e.com</link><description>sin items</description>'
            '</channel></rss>\n', encoding="utf-8")

    def _corre(self, args, env_extra=None):
        import os
        import subprocess
        import sys
        env = dict(os.environ)
        env.pop("SIBILA_HMAC_KEY", None)  # el aviso HMAC debe depender del entorno del test
        deps = RAIZ.parent / "deps"  # sandbox: $HOME efímero → deps en pip --target persistente
        if deps.is_dir():
            env["PYTHONPATH"] = str(deps) + os.pathsep + env.get("PYTHONPATH", "")
        if env_extra:
            env.update(env_extra)
        return subprocess.run([sys.executable, "-m", "sibila", *args], cwd=RAIZ, env=env,
                              capture_output=True, text=True, errors="replace", timeout=120)

    def _env_bd(self, subdir="datos"):
        datos = self.tmp / f"{subdir}_{self._testMethodName}"
        return datos, {"SIBILA_DATA_DIR": str(datos),
                       "SIBILA_DB_PATH": str(datos / "sibila.db")}

    def test_sin_db_solo_parsea(self):
        r = self._corre(["ingesta", "--fuentes", str(RAIZ / "tests" / "fuentes_test.toml"),
                         "--sin-db"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("documentos parseados", r.stdout)
        self.assertIn("--sin-db, nada persistido", r.stdout)
        self.assertIn("[INFO] modo sin-db: nada se escribió", r.stdout)

    def test_persiste_en_bd(self):
        datos, env = self._env_bd("datos_persiste")
        r1 = self._corre(["init"], env)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = self._corre(["ingesta", "--fuentes", str(RAIZ / "tests" / "fuentes_test.toml")], env)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("nuevos", r2.stdout)
        self.assertIn("[AVISO] sin hmac_key: author_hash quedará NULL", r2.stdout)  # C-B2-10
        self.assertIn("[INFO] ingesta:", r2.stdout)  # resumen total
        con = sqlite3.connect(str(datos / "sibila.db"))
        n = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        cur = con.execute("SELECT COUNT(*) FROM conector_cursor").fetchone()[0]
        mets = con.execute("SELECT COUNT(*) FROM ops_metrics").fetchone()[0]
        con.close()
        self.assertEqual(n, 12)   # 3 por fuente
        self.assertEqual(cur, 4)  # un cursor por fuente
        self.assertEqual(mets, 16)  # 4 métricas × 4 fuentes (D-B2-06)
        # segunda pasada: 0 nuevos (idempotencia extremo a extremo)
        r3 = self._corre(["ingesta", "--fuentes", str(RAIZ / "tests" / "fuentes_test.toml")], env)
        self.assertIn("0 nuevos", r3.stdout)

    def test_cero_documentos_aviso_y_304_ok(self):
        """rev. M12/M7: 200-vacío → [AVISO] (¿feed roto o vacío?); repetición sin cambios
        (cursor idéntico, equivalente 304) → [OK] sin novedades. Nunca [OK] silencioso."""
        datos, env = self._env_bd("datos_vacio")
        toml = self.tmp / f"fuentes_vacio_{self._testMethodName}.toml"
        toml.write_text(f'[lobsters]\nhabilitada = true\nfixture = "{self.fixture_vacio}"\n',
                        encoding="utf-8")
        r1 = self._corre(["init"], env)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = self._corre(["ingesta", "--fuentes", str(toml)], env)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("[AVISO] lobsters: 0 documentos", r2.stdout)
        r3 = self._corre(["ingesta", "--fuentes", str(toml)], env)
        self.assertIn("[OK] lobsters: sin novedades", r3.stdout)

    def test_aislamiento_por_fuente_y_exit_1(self):
        """rev. Hamilton M4: una fuente caída NO aborta la corrida; la sana persiste;
        exit 1 por el FALLO parcial."""
        datos, env = self._env_bd("datos_aisla")
        toml = self.tmp / f"fuentes_aisla_{self._testMethodName}.toml"
        toml.write_text(
            '[lobsters]\nhabilitada = true\n'
            f'fixture = "{RAIZ / "tests" / "fixtures" / "conectores" / "lobsters.xml"}"\n\n'
            '[reddit]\nhabilitada = true\nfixture = "no/existe/este.json"\n',
            encoding="utf-8")
        r1 = self._corre(["init"], env)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = self._corre(["ingesta", "--fuentes", str(toml)], env)
        self.assertEqual(r2.returncode, 1, r2.stdout + r2.stderr)
        self.assertIn("[FALLO] reddit:", r2.stdout)
        self.assertIn("[OK] lobsters:", r2.stdout)
        self.assertNotIn("Traceback", r2.stdout + r2.stderr)
        con = sqlite3.connect(str(datos / "sibila.db"))
        n = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        con.close()
        self.assertEqual(n, 3)  # lobsters persistió pese al reddit caído

    def test_validaciones_exit_2(self):
        r = self._corre(["ingesta", "--en-vivo", "--fixture", "x.json", "--fuente", "reddit"])
        self.assertEqual(r.returncode, 2)
        r = self._corre(["ingesta", "--limite", "0"])
        self.assertEqual(r.returncode, 2)
        r = self._corre(["ingesta", "--fixture", "x.json"])  # sin --fuente
        self.assertEqual(r.returncode, 2)
        r = self._corre(["ingesta", "--fixture", "x.json", "--fuente", "reddit",
                         "--fuente", "lobsters"])  # rev. Dijkstra M3: multi-fuente
        self.assertEqual(r.returncode, 2)

    def test_fixture_individual(self):
        r = self._corre(["ingesta", "--fuente", "lobsters", "--sin-db",
                         "--fixture", str(RAIZ / "tests" / "fixtures" / "conectores" / "lobsters.xml")])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lobsters", r.stdout)


if __name__ == "__main__":
    unittest.main()

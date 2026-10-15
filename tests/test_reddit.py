"""T1 · conectores/reddit.py contra fixture JSON (sin red) + fallback RSS con sesión stub."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sibila.conectores.base import HttpError
from sibila.conectores.reddit import Reddit, parsear

FIX = Path(__file__).parent / "fixtures" / "conectores" / "reddit.json"
UTC = timezone.utc


class TestParsear(unittest.TestCase):
    def setUp(self):
        self.docs, self.cont = parsear(FIX.read_text(encoding="utf-8"))

    def test_lote(self):
        self.assertEqual(len(self.docs), 4)      # p1, p2, p3(repost), p4
        self.assertEqual(self.cont["saltadas"], 2)  # t1 y data null

    def test_fecha_epoch_a_utc(self):
        p1 = [d for d in self.docs if d.author_raw == "alice"][0]
        self.assertEqual(p1.published_at, datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC))

    def test_sin_fecha_none(self):
        p2 = [d for d in self.docs if d.author_raw == "bob"][0]
        self.assertIsNone(p2.published_at)

    def test_permalink_fallback(self):
        p4 = [d for d in self.docs if d.author_raw == "dave"][0]
        self.assertEqual(p4.url, "https://www.reddit.com/r/worldnews/comments/p4/self_post/")

    def test_titulo_y_cuerpo(self):
        p1 = [d for d in self.docs if d.author_raw == "alice"][0]
        self.assertIn("Noticia mundial", p1.body)
        self.assertIn("Cuerpo con", p1.body)

    def test_tipos_rotos_saltados_no_rompen_lote(self):  # rev. Dijkstra B4
        """data como LISTA y url como ENTERO son formas reales que la API devuelve;
        antes tumbaban la fuente cada ciclo (AttributeError no traducido)."""
        texto = json.dumps({"data": {"children": [
            {"kind": "t3", "data": ["no", "soy", "dict"]},
            {"kind": "t3", "data": {"url": 123, "title": "url entera", "selftext": "x",
                                    "created_utc": 1784541600, "author": "eva"}},
            {"kind": "t3", "data": {"url": "https://e.com/ok", "title": "ok",
                                    "selftext": "", "created_utc": 1784541600,
                                    "author": "amy"}},
            "ni-siquiera-dict",
        ]}})
        docs, cont = parsear(texto)
        self.assertEqual(cont["saltadas"], 2)      # data lista + child no-dict
        self.assertEqual(len(docs), 2)             # url-entera (doc sin url) + ok
        eva = [d for d in docs if d.author_raw == "eva"][0]
        self.assertIsNone(eva.url)                 # url 123 jamás llega como url
        self.assertEqual(eva.published_at, datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC))

    def test_raiz_no_listing_valueerror(self):
        with self.assertRaises(ValueError):
            parsear(json.dumps(["no", "es", "listing"]))
        with self.assertRaises(ValueError):
            parsear(json.dumps({"sin": "data"}))


class TestFetch(unittest.TestCase):
    def test_emitidos_y_dedup_url(self):
        c = Reddit({"fixture": str(FIX)})
        docs, cursor = c.fetch(c.cfg, None)
        self.assertEqual(len(docs), 3)  # el repost (misma url) fuera
        docs2, _ = c.fetch(c.cfg, cursor)
        self.assertEqual(len(docs2), 0)

    def test_json_invalido_es_httperror_parse(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("esto no es json{")
            ruta = f.name
        c = Reddit({"fixture": ruta})
        with self.assertRaises(HttpError) as ctx:
            c.fetch(c.cfg, None)
        self.assertEqual(ctx.exception.codigo, "parse")

    def test_fallback_a_rss(self):
        """El .json da 403; el .rss responde 200 con un feed → documentos parseados."""
        from tests.test_conectores_base import SesionStub, resp
        rss = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
               b'<item><title>via rss</title><link>https://www.reddit.com/r/x/1</link>'
               b'<guid>https://www.reddit.com/r/x/1</guid>'
               b'<pubDate>Mon, 20 Jul 2026 12:00:00 +0200</pubDate>'
               b'<description>cuerpo rss</description></item></channel></rss>')
        guion = {"json": resp(403), "rss": resp(200, rss)}

        class S:
            def get(self, url, headers=None, timeout=None):
                return guion["rss"] if url.endswith(".rss") else guion["json"]

        c = Reddit({"url": "https://www.reddit.com/r/x/new/.json"})
        docs, _ = c.fetch(c.cfg, None, sesion=S(), dormir=lambda _: None)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].published_at, datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC))

    def test_304_sin_novedades(self):
        from tests.test_conectores_base import resp

        class S:
            def get(self, url, headers=None, timeout=None):
                return resp(304)

        c = Reddit({"url": "https://www.reddit.com/r/x/new/.json"})
        docs, cursor = c.fetch(c.cfg, None, sesion=S(), dormir=lambda _: None)
        self.assertEqual(docs, [])
        self.assertIsNone(cursor)

    def test_raiz_invalida_en_vivo_cae_a_rss(self):  # rev. Dijkstra M4
        """.json 200 pero con raíz no-listing → UN intento a .rss (el plan lo fija)."""
        from tests.test_conectores_base import resp
        rss = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
               b'<item><title>via rss</title><link>https://www.reddit.com/r/x/2</link>'
               b'<pubDate>Mon, 20 Jul 2026 12:00:00 +0200</pubDate>'
               b'<description>cuerpo rss</description></item></channel></rss>')
        llamadas = []

        class S:
            def get(self, url, headers=None, timeout=None):
                llamadas.append(url)
                if url.endswith(".rss"):
                    return resp(200, rss)
                return resp(200, b'["raiz", "no-listing"]')

        c = Reddit({"url": "https://www.reddit.com/r/x/new/.json"})
        docs, _ = c.fetch(c.cfg, None, sesion=S(), dormir=lambda _: None)
        self.assertEqual(len(docs), 1)
        self.assertTrue(any(u.endswith(".rss") for u in llamadas))

    def test_500_no_cae_a_rss(self):  # rev. Dijkstra M4
        """Los errores de red (5xx agotados) NO disparan fallback: son FALLO visible."""
        from tests.test_conectores_base import resp
        llamadas = []

        class S:
            def get(self, url, headers=None, timeout=None):
                llamadas.append(url)
                return resp(500)

        c = Reddit({"url": "https://www.reddit.com/r/x/new/.json"})
        with self.assertRaises(HttpError) as ctx:
            c.fetch(c.cfg, None, sesion=S(), dormir=lambda _: None)
        self.assertEqual(ctx.exception.codigo, "http_500")
        self.assertFalse(any(u.endswith(".rss") for u in llamadas))


if __name__ == "__main__":
    unittest.main()

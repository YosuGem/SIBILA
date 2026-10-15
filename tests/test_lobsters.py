"""T1 · conectores/lobsters.py contra fixture con forma real (sin red).
Nota: para RSS el body es la DESCRIPTION (título solo de respaldo); las búsquedas
de los tests apuntan al contenido de la description."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sibila.conectores.base import HttpError
from sibila.conectores.lobsters import Lobsters, parsear_feed

FIX = Path(__file__).parent / "fixtures" / "conectores" / "lobsters.xml"
UTC = timezone.utc


def carga():
    return FIX.read_bytes()


class TestParsear(unittest.TestCase):
    def test_lote(self):
        docs, cont = parsear_feed(carga(), fuente="lobsters")
        self.assertEqual(len(docs), 4)          # 3 válidos + 1 repost (dup se quita en fetch)
        self.assertEqual(cont["saltadas"], 1)   # item sin link/guid y sin cuerpo

    def test_offset_mas_0200_a_utc_exacto(self):  # TP-N11
        docs, _ = parsear_feed(carga(), fuente="lobsters")
        primero = [d for d in docs if "Discusion" in d.body][0]
        self.assertEqual(primero.published_at, datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC))
        self.assertEqual(primero.published_at.utcoffset().total_seconds(), 0)

    def test_offset_menos_0500_a_utc(self):
        docs, _ = parsear_feed(carga(), fuente="lobsters")
        quinto = [d for d in docs if "-0500" in d.body][0]
        self.assertEqual(quinto.published_at, datetime(2026, 7, 20, 4, 30, 0, tzinfo=UTC))

    def test_sin_fecha_none(self):
        docs, _ = parsear_feed(carga(), fuente="lobsters")
        sinfecha = [d for d in docs if "sin pubDate" in d.body][0]
        self.assertIsNone(sinfecha.published_at)

    def test_malformado_saltado_no_rompe_lote(self):
        docs, cont = parsear_feed(carga(), fuente="lobsters")
        self.assertFalse(any(d.url is None and not d.body for d in docs))

    def test_body_con_html_crudo(self):
        docs, _ = parsear_feed(carga(), fuente="lobsters")
        primero = docs[0]
        self.assertIn("<b>HTML</b>", primero.body)  # el HTML va CRUDO (decisión: NLP lo trata después)

    def test_bozo_irrecuperable_es_httperror_parse(self):
        with self.assertRaises(HttpError) as ctx:
            parsear_feed(b"<rss><channel><it", fuente="lobsters")
        self.assertEqual(ctx.exception.codigo, "parse")

    def test_bozo_con_entradas_se_procesa(self):  # plan T-C4 / rev. Hamilton E2
        """XML TRUNCADO (bozo=1) pero con entradas completas: se procesan las válidas
        con aviso, no se descarta el lote."""
        truncado = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
                    b'<item><title>completa</title><link>https://e.com/1</link>'
                    b'<pubDate>Mon, 20 Jul 2026 12:00:00 +0200</pubDate>'
                    b'<description>entrada completa previa al corte</description></item>'
                    b'<item><title>cortada por la mit')
        docs, cont = parsear_feed(truncado, fuente="lobsters")
        self.assertEqual(len(docs), 1)
        self.assertIn("entrada completa", docs[0].body)

    def test_etag_minusculas_se_guarda_y_reenvia(self):  # rev. Dijkstra/Hamilton M8
        """HTTP/2 manda las cabeceras en minúsculas: el ETag debe guardarse en el cursor
        y reenviarse como If-None-Match; el servidor que lo reconoce responde 304."""
        from tests.test_conectores_base import resp
        rss = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
               b'<item><title>a</title><link>https://e.com/1</link>'
               b'<description>contenido del item</description></item></channel></rss>')
        enviadas = []

        class S:
            def __init__(self, guion):
                self.guion = list(guion)
            def get(self, url, headers=None, timeout=None):
                enviadas.append(dict(headers or {}))
                return self.guion.pop(0)

        c = Lobsters({"url": "https://e.com/rss"})
        # pasada 1: 200 con etag SOLO en minúsculas (forma HTTP/2)
        docs, cursor = c.fetch(c.cfg, None,
                               sesion=S([resp(200, rss, {"etag": "W/1", "last-modified": "Mon"})]),
                               dormir=lambda _: None)
        self.assertEqual(len(docs), 1)
        self.assertIn('"etag":"W/1"', cursor)  # dump_cursor con separators compactos
        # pasada 2: el servidor ve If-None-Match y responde 304 → ([], cursor intacto)
        docs2, cursor2 = c.fetch(c.cfg, cursor, sesion=S([resp(304)]),
                                 dormir=lambda _: None)
        self.assertEqual(docs2, [])
        self.assertEqual(cursor2, cursor)
        self.assertEqual(enviadas[1].get("If-None-Match"), "W/1")
        self.assertEqual(enviadas[1].get("If-Modified-Since"), "Mon")


class TestFetchConFixture(unittest.TestCase):
    def test_emitidos_y_dedup_y_cursor(self):
        c = Lobsters({"fixture": str(FIX)})
        docs, cursor = c.fetch(c.cfg, None)
        self.assertEqual(len(docs), 3)  # repost fuera (mismo link)
        # segunda pasada con el cursor devuelto: todo visto
        docs2, _ = c.fetch(c.cfg, cursor)
        self.assertEqual(len(docs2), 0)


if __name__ == "__main__":
    unittest.main()

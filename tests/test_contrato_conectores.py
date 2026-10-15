"""T1 · contrato transversal de los 4 conectores (Hopper §7): mismo protocolo para todos."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import json
import unittest
from pathlib import Path

from sibila.conectores import REGISTRO
from sibila.conectores.base import parse_cursor
from sibila.ingesta import es_fecha_valida  # la frontera del contrato vive en ingesta (D-B2-07)

FIXDIR = Path(__file__).parent / "fixtures" / "conectores"
CASOS = [
    ("reddit", "reddit.json"),
    ("lobsters", "lobsters.xml"),
    ("mastodon", "mastodon.xml"),
    ("4chan", "cuatrochan.json"),
]


class TestContrato(unittest.TestCase):
    def test_contrato_lote_y_cursor(self):
        for nombre, fichero in CASOS:
            with self.subTest(fuente=nombre):
                c = REGISTRO[nombre]({"fixture": str(FIXDIR / fichero)})
                docs, cursor = c.fetch(c.cfg, None)
                self.assertGreater(len(docs), 0)
                self.assertIsInstance(cursor, str)
                self.assertIsInstance(parse_cursor(cursor), dict)  # cursor siempre recuperable
                for d in docs:
                    self.assertEqual(d.fuente, nombre)
                    self.assertTrue(d.url is None or d.url.startswith(("http://", "https://")))
                    self.assertIsInstance(d.body, str)
                    self.assertTrue(d.crudo)  # respaldo de hash siempre presente
                    if d.published_at is not None:
                        self.assertTrue(es_fecha_valida(d.published_at),
                                        f"{nombre}: {d.published_at!r} no es UTC estricta")
                # segunda pasada con el cursor: todo conocido
                docs2, _ = c.fetch(c.cfg, cursor)
                self.assertEqual(len(docs2), 0, f"{nombre}: el cursor no filtra lo ya visto")

    def test_determinismo(self):
        for nombre, fichero in CASOS:
            with self.subTest(fuente=nombre):
                c1 = REGISTRO[nombre]({"fixture": str(FIXDIR / fichero)})
                c2 = REGISTRO[nombre]({"fixture": str(FIXDIR / fichero)})
                d1, cur1 = c1.fetch(c1.cfg, None)
                d2, cur2 = c2.fetch(c2.cfg, None)
                self.assertEqual(len(d1), len(d2))
                self.assertEqual(cur1, cur2, f"{nombre}: mismo fixture debe dar mismo cursor")


if __name__ == "__main__":
    unittest.main()

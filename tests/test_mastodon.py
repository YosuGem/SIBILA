"""T1 · conectores/mastodon.py contra fixture Atom (sin red)."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sibila.conectores.mastodon import Mastodon

FIX = Path(__file__).parent / "fixtures" / "conectores" / "mastodon.xml"
UTC = timezone.utc


class TestMastodon(unittest.TestCase):
    def setUp(self):
        self.c = Mastodon({"fixture": str(FIX)})
        self.docs, self.cursor = self.c.fetch(self.c.cfg, None)

    def test_lote(self):
        self.assertEqual(len(self.docs), 3)  # 101, 102 y 103; 104 saltada; dup id fuera

    def test_urn_nunca_es_url(self):  # T-C3
        d103 = [d for d in self.docs if "sinvinculo" in (d.author_raw or "")][0]
        self.assertIsNone(d103.url)
        self.assertTrue(d103.body)  # y el doc SÍ se conserva con contenido

    def test_offset_0200_a_utc(self):  # TP-N11
        d101 = [d for d in self.docs if "101" in d.crudo][0]
        self.assertEqual(d101.published_at, datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC))

    def test_sin_published_none(self):
        d102 = [d for d in self.docs if "102" in d.crudo][0]
        self.assertIsNone(d102.published_at)

    def test_segunda_pasada_cero(self):
        docs2, _ = self.c.fetch(self.c.cfg, self.cursor)
        self.assertEqual(len(docs2), 0)

    def test_url_derivada(self):
        self.assertEqual(Mastodon.url_de({"instancia": "m.cafe", "tag": "zen"}),
                         "https://m.cafe/tags/zen.atom")

    def test_clave_reserva_no_colisiona(self):  # rev. Dijkstra B3 / Hamilton B2
        """Dos toots SIN <link> del mismo autor con contenido distinto: con la clave
        vieja (prefijo crudo[:80]) el segundo era falso dup PERMANENTE vía cursor.
        Con 'h:'+sha256(crudo)[:32] ambos se emiten."""
        import tempfile
        pref = "x" * 120  # fuerza prefijos crudos idénticos en los primeros 80 chars
        atom = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            f'<entry><id>tag:x.com,2026:a1</id><author><name>ana</name></author>'
            f'<content>{pref} contenido uno distinto al final</content></entry>'
            f'<entry><id>tag:x.com,2026:a2</id><author><name>ana</name></author>'
            f'<content>{pref} contenido dos DISTINTO del todo</content></entry>'
            '</feed>')
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False,
                                         encoding="utf-8") as f:
            f.write(atom)
            ruta = f.name
        c = Mastodon({"fixture": ruta})
        docs, cursor = c.fetch(c.cfg, None)
        self.assertEqual(len(docs), 2)  # los dos sobreviven
        docs2, _ = c.fetch(c.cfg, cursor)
        self.assertEqual(len(docs2), 0)  # y el cursor sí recuerda a AMBOS


if __name__ == "__main__":
    unittest.main()

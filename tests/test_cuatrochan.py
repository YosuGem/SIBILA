"""T1 · conectores/cuatrochan.py contra fixture catalog.json (sin red)."""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sibila.conectores.cuatrochan import CuatroChan, parsear

FIX = Path(__file__).parent / "fixtures" / "conectores" / "cuatrochan.json"
UTC = timezone.utc


class TestParsear(unittest.TestCase):
    def setUp(self):
        self.docs, self.cont = parsear(FIX.read_text(encoding="utf-8"), tablon="pol")

    def test_lote(self):
        self.assertEqual(len(self.docs), 4)      # 900001, 900002, 900001-p2, 900006
        self.assertEqual(self.cont["saltadas"], 2)  # sin 'no' y hilo-imagen

    def test_sin_subject_conservado(self):  # el 44 % real de 4chan
        self.assertTrue(any("sin subject" in d.body for d in self.docs))

    def test_hilo_imagen_saltado(self):
        self.assertFalse(any("900004" in d.url for d in self.docs))

    def test_fechas_epoch(self):
        d1 = [d for d in self.docs if "900001" in d.url][0]
        self.assertEqual(d1.published_at, datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC))
        d2 = [d for d in self.docs if "900002" in d.url][0]
        self.assertEqual(d2.published_at, datetime(2026, 7, 20, 8, 0, 0, tzinfo=UTC))

    def test_sin_time_none(self):
        d6 = [d for d in self.docs if "900006" in d.url][0]
        self.assertIsNone(d6.published_at)

    def test_paginas_limite(self):
        docs1, _ = parsear(FIX.read_text(encoding="utf-8"), tablon="pol", paginas=1)
        self.assertEqual(len(docs1), 2)  # solo página 1

    def test_tipos_rotos_no_rompen_lote(self):  # rev. Dijkstra B4
        """sub ENTERO (tipo realmente visto), página no-dict, hilo no-dict, 'no' como
        string: todo se cuenta y el lote sigue; la raíz no-lista es ValueError."""
        texto = json.dumps([
            {"threads": [
                {"no": 900010, "sub": 42, "com": "hilo con sub entero", "time": 1784541600},
                "ni-siquiera-dict",
                {"no": "900011", "com": "no como string"},
            ]},
            ["pagina-no-dict"],
            {"threads": [{"no": 900012, "com": "hilo bueno final", "time": 1784541600}]},
        ])
        docs, cont = parsear(texto)
        self.assertEqual(cont["saltadas"], 3)  # no-dict + no-string + página-no-dict
        self.assertEqual(len(docs), 2)         # sub-entero (conservado) + bueno final
        self.assertTrue(any("sub entero" in d.body for d in docs))
        with self.assertRaises(ValueError):
            parsear(json.dumps({"no": "soy una lista de páginas"}))


class TestFetch(unittest.TestCase):
    def test_emitidos_y_dedup_entre_paginas(self):
        c = CuatroChan({"fixture": str(FIX), "paginas": 3})
        docs, cursor = c.fetch(c.cfg, None)
        self.assertEqual(len(docs), 3)  # 900001 de página 2 fuera
        docs2, _ = c.fetch(c.cfg, cursor)
        self.assertEqual(len(docs2), 0)

    def test_304_alcanzable_y_validadores(self):  # rev. Hamilton M8
        """4chan también envía If-None-Match/If-Modified-Since del cursor y la rama 304
        es alcanzable: ([], cursor intacto)."""
        from tests.test_conectores_base import resp
        enviadas = []

        class S:
            def get(self, url, headers=None, timeout=None):
                enviadas.append(dict(headers or {}))
                return resp(304)

        c = CuatroChan({"tablon": "pol"})
        cursor_in = '{"vistos": [], "etag": "W/9", "modified": "Mar"}'
        docs, cursor = c.fetch(c.cfg, cursor_in, sesion=S(), dormir=lambda _: None)
        self.assertEqual(docs, [])
        self.assertEqual(cursor, cursor_in)
        self.assertEqual(enviadas[0].get("If-None-Match"), "W/9")
        self.assertEqual(enviadas[0].get("If-Modified-Since"), "Mar")


if __name__ == "__main__":
    unittest.main()

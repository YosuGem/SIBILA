"""T1 · conectores/base.py: contrato RawDoc, cursor, claves de dedup y descarga con stubs.
La validación del contrato y los hashes de persistencia viven en sibila.ingesta (D-B2-07):
sus tests están en test_ingesta.py."""
import unittest
from pathlib import Path

import requests

from sibila.conectores import base
from sibila.conectores.base import (HttpError, RawDoc, cargar_fuentes, clave_doc,
                                    descargar, dump_cursor, parse_cursor)

UTC = __import__("datetime").timezone.utc


def doc(**kw):
    base_ = dict(fuente="reddit", url="https://e.com/1", author_raw="nora",
                 published_at=None, body="texto", crudo="x", lang=None)
    base_.update(kw)
    return RawDoc(**base_)


class TestClaveDoc(unittest.TestCase):
    def test_url_si_hay(self):
        self.assertEqual(clave_doc(doc(url="https://e.com/9")), "https://e.com/9")

    def test_reserva_hash_no_prefijo(self):
        """rev. Dijkstra B3 / Hamilton B2: crudo[:80] colisionaba entre docs distintos
        del mismo autor sin link → falso dup PERMANENTE vía cursor. La clave de reserva
        es 'h:' + sha256(crudo)[:32] (plan Hopper §4)."""
        a = doc(url=None, crudo="A" * 200 + "final-distinto-a")
        b = doc(url=None, crudo="A" * 200 + "final-distinto-b")
        self.assertNotEqual(clave_doc(a), clave_doc(b))     # mismo prefijo[:80], claves ≠
        self.assertTrue(clave_doc(a).startswith("h:"))
        self.assertEqual(len(clave_doc(a)), 2 + 32)
        self.assertEqual(clave_doc(a), clave_doc(a))        # determinista


class TestCursor(unittest.TestCase):
    def test_cursor_corrupto_nunca_tumba(self):
        self.assertEqual(parse_cursor("no es json{"), {})
        self.assertEqual(parse_cursor(None), {})
        self.assertEqual(parse_cursor('[1,2]'), {})
        ida = dump_cursor({"vistos": ["a", "b"], "etag": "E1"})
        self.assertEqual(parse_cursor(ida), {"etag": "E1", "vistos": ["a", "b"]})

    def test_vistos_tipo_roto_no_tumba(self):
        """rev. Dijkstra M10: {'vistos': 123} o elementos no-texto lanzaban TypeError
        y tumbaban la fuente cada ciclo → vacío + aviso, nunca excepción."""
        self.assertFalse(base.CursorVistos.desde_dict({"vistos": 123}).visto("x"))
        self.assertFalse(base.CursorVistos.desde_dict({"vistos": ["a", 7]}).visto("a"))
        cv = base.CursorVistos.desde_dict({"vistos": ["a", "b"]})
        self.assertTrue(cv.visto("a"))

    def test_cursor_vistos_recorte(self):
        cv = base.CursorVistos(maximo=3)
        for i in range(5):
            cv.agregar(f"k{i}")
        cv.recortar()
        self.assertFalse(cv.visto("k0"))
        self.assertFalse(cv.visto("k1"))
        self.assertTrue(cv.visto("k4"))
        cv2 = base.CursorVistos.desde_dict(cv.como_dict())
        self.assertTrue(cv2.visto("k4"))

    def test_tope_por_defecto_1000(self):
        """Plan Hopper §4: tope 1000 FIFO (/pol/ mueve ~200 hilos/pasada)."""
        self.assertEqual(base.CursorVistos().maximo, 1000)


class SesionStub:
    """Sesión inyectable: sirve respuestas en orden o lanza ConnectionError/Timeout."""

    def __init__(self, guion):
        self.guion = list(guion)
        self.llamadas = []
        self.timeouts = []

    def get(self, url, headers=None, timeout=None):
        self.llamadas.append(url)
        self.timeouts.append(timeout)
        paso = self.guion.pop(0)
        if paso == "red":
            raise requests.ConnectionError("caída simulada")
        if paso == "timeout":
            raise requests.Timeout("timeout simulado")
        return paso


def resp(codigo, contenido=b"x", cabeceras=None):
    class R:
        status_code = codigo
        content = contenido
        headers = cabeceras or {}
    return R()


class TestDescargar(unittest.TestCase):
    def test_200_directo_y_timeout_tupla(self):
        """Perfil del plan (rev. Dijkstra E4): timeout=(5,20) tupla SIEMPRE."""
        s = SesionStub([resp(200, b"ok")])
        contenido, cab = descargar(s, "https://e.com")
        self.assertEqual(contenido, b"ok")
        self.assertEqual(s.timeouts, [(5, 20)])

    def test_cabeceras_en_minusculas(self):
        """rev. Dijkstra M8: HTTP/2 manda las cabeceras en minúsculas; el ETag debe
        encontrarse igual → las cabeceras devueltas van normalizadas."""
        _c, cab = descargar(SesionStub([resp(200, cabeceras={"ETag": "W/1"})]), "https://e.com")
        self.assertEqual(cab.get("etag"), "W/1")

    def test_304_devuelve_none(self):
        """304 → (None, cabeceras): sin novedades; el fetch devuelve ([], cursor)."""
        contenido, _cab = descargar(SesionStub([resp(304)]), "https://e.com")
        self.assertIsNone(contenido)

    def test_429_respeta_retry_after(self):
        esperas = []
        s = SesionStub([resp(429, cabeceras={"Retry-After": "7"}), resp(200, b"ok")])
        contenido, _ = descargar(s, "https://e.com", espera=1, dormir=esperas.append)
        self.assertEqual(contenido, b"ok")
        self.assertEqual(esperas, [7])  # honra el entero del servidor

    def test_500_reintenta_y_403_no(self):
        s = SesionStub([resp(500), resp(200, b"ok")])
        contenido, _ = descargar(s, "https://e.com", dormir=lambda _: None)
        self.assertEqual(contenido, b"ok")
        with self.assertRaises(HttpError) as ctx:
            descargar(SesionStub([resp(403), resp(200)]), "https://e.com", dormir=lambda _: None)
        self.assertEqual(ctx.exception.codigo, "http_403")

    def test_red_caida_tras_intentos(self):
        s = SesionStub(["red", "red", "red"])
        with self.assertRaises(HttpError) as ctx:
            descargar(s, "https://e.com", reintentos=2, dormir=lambda _: None)
        self.assertEqual(ctx.exception.codigo, "red")
        self.assertEqual(len(s.llamadas), 3)
        self.assertIn("sin respuesta", str(ctx.exception))

    def test_timeout_reintenta_otra_requestexception_no(self):
        """Reintenta SOLO 429/5xx/Timeout/ConnectionError (plan Hopper §5)."""
        s = SesionStub(["timeout", resp(200, b"ok")])
        contenido, _ = descargar(s, "https://e.com", dormir=lambda _: None)
        self.assertEqual(contenido, b"ok")

        class StubRaro(SesionStub):
            def get(self, url, headers=None, timeout=None):
                raise requests.TooManyRedirects("bucle")
        with self.assertRaises(HttpError) as ctx:
            descargar(StubRaro([]), "https://e.com", dormir=lambda _: None)
        self.assertEqual(ctx.exception.codigo, "red")

    def test_excepcion_no_requests_tambien_es_httperror(self):  # rev. Dijkstra N2 r2
        """El docstring promete 'NUNCA lanza excepciones crudas': un fallo de la sesión
        que NO sea de requests (bug del operador, stub mal hecho) sale como HttpError."""
        class StubBug(SesionStub):
            def get(self, url, headers=None, timeout=None):
                raise AttributeError("stub mal programado")
        with self.assertRaises(HttpError) as ctx:
            descargar(StubBug([]), "https://e.com", dormir=lambda _: None)
        self.assertEqual(ctx.exception.codigo, "inesperado")


class TestCargarFuentes(unittest.TestCase):
    def test_carga_y_fixture_relativo(self):
        fuentes = cargar_fuentes(Path(__file__).parent / "fuentes_test.toml")
        self.assertEqual(set(fuentes), {"reddit", "lobsters", "mastodon", "4chan"})
        for cfg in fuentes.values():
            self.assertTrue(Path(cfg["fixture"]).is_absolute())
            self.assertTrue(Path(cfg["fixture"]).exists())

    def test_clave_desconocida(self, ):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write('[lobsters]\nurls = "x"\n')
            ruta = f.name
        with self.assertRaises(ValueError) as ctx:
            cargar_fuentes(ruta)
        self.assertIn("urls", str(ctx.exception))

    def test_nombre_desconocido(self):
        from sibila.conectores import conectores_habilitados
        with self.assertRaises(ValueError):
            conectores_habilitados({"tiktok": {"habilitada": True}})

    def test_habilitados(self):
        from sibila.conectores import conectores_habilitados
        fuentes = cargar_fuentes(Path(__file__).parent / "fuentes_test.toml")
        hab = conectores_habilitados(fuentes)
        self.assertEqual({c.nombre for c in hab}, {"reddit", "lobsters", "mastodon", "4chan"})
        for c in hab:
            self.assertIsInstance(c.cfg, dict)


if __name__ == "__main__":
    unittest.main()

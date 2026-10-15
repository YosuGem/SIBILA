"""Tests puros de procesado/limpieza.py y procesado/calidad.py."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import unittest

from sibila.procesado.calidad import score
from sibila.procesado.limpieza import limpiar

T1 = ("la economia europea entra en recession tecnica mientras el bce "
      "mantiene los tipos de interes y la inflacion sigue por encima del "
      "objetivo")
T2 = "jaja jaja jaja"


class TestLimpieza(unittest.TestCase):
    def test_url_y_email(self):
        self.assertEqual(limpiar("mira https://example.com/x y www.otra.es fin"),
                         "mira y fin")
        self.assertEqual(limpiar("escribe a pepe@example.com ya"),
                         "escribe a ya")

    def test_html_y_entidades(self):
        self.assertEqual(limpiar("<b>Hola</b> &amp; <a href='x'>mundo</a>"),
                         "hola & mundo")

    def test_citas(self):
        # "> " (con espacio) se elimina entera; ">implicando" (greentext) vive
        self.assertEqual(limpiar("texto\n> cita de correo\n>implicando cosas"),
                         "texto >implicando cosas")

    def test_nfkc_y_casefold(self):
        self.assertEqual(limpiar("ﬁesta"), "fiesta")   # ligadura ﬁ → fi
        self.assertEqual(limpiar("  HoLa\tMuNdo  "), "hola mundo")

    def test_vacio(self):
        self.assertEqual(limpiar(""), "")
        self.assertEqual(limpiar("https://x.co <i></i>"), "")

    def test_idempotencia(self):
        sucio = ("  <p>HoLa &amp; ADIÓS</p> https://t.co/abc a@b.c\n"
                 "> cita\n>implicando ﬁn\t\tdel  texto")
        self.assertEqual(limpiar(limpiar(sucio)), limpiar(sucio))

    def test_tipo_incorrecto(self):
        with self.assertRaises(ValueError):
            limpiar(None)


class TestCalidad(unittest.TestCase):
    def test_vectores_congelados(self):
        self.assertEqual(score(T1, "es", 0.93), 0.6331)  # 23 palabras, H=3,8444
        self.assertEqual(score(T2, "es", 0.40), 0.2457)  # 3 palabras, H=1,4488

    def test_cero(self):
        self.assertEqual(score("", None, 0.0), 0.0)
        self.assertEqual(score("", None), 0.0)

    def test_mutante_h7_sin_confianza_cambia_resultado(self):
        # Un test que pasa igual con y sin `confianza` es un test muerto:
        # omitir el parámetro (q_idioma=0) DEBE cambiar el score.
        self.assertNotEqual(score(T1, "es"), score(T1, "es", 0.93))
        self.assertEqual(score(T1, None, 0.93), score(T1, None, 0.0))

    def test_rango(self):
        for texto in (T1, T2, "a b c", "x" * 5000):
            self.assertTrue(0.0 <= score(texto, "es", 0.5) <= 1.0)


if __name__ == "__main__":
    unittest.main()

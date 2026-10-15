"""Tests puros de procesado/ngramas.py: vector congelado de clustering
(§4.8) con desempate alfabético y singleton; regla de stopwords en n-gramas."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import unittest

from sibila.procesado.ngramas import Cluster, StatsDia, clusterizar, extraer
from sibila.procesado.stopwords import EN, ES, STOPWORDS_VERSION, stopwords


class TestStopwords(unittest.TestCase):
    def test_version(self):
        self.assertEqual(STOPWORDS_VERSION, "sw-1")

    def test_listas(self):
        self.assertIn("el", ES)
        self.assertIn("the", EN)
        self.assertNotIn("inflacion", ES)   # los vectores congelados la exigen
        self.assertEqual(stopwords("fr"), frozenset())
        self.assertEqual(stopwords(None), frozenset())


class TestExtraer(unittest.TestCase):
    def test_terminos_content_words(self):
        # "hoy" es stopword ES (Snowball): queda fuera de los términos
        n = extraer("el banco y la inflacion de hoy", "es")
        self.assertEqual(n.terminos, frozenset({"banco", "inflacion"}))

    def test_ngramas_sin_stopwords_preservan_adyacencia(self):
        # "banco central" no muere por la stopword intermedia: se quitan las
        # stopwords del idioma y se forma el n-grama sobre la adyacencia
        # resultante.
        n = extraer("el banco de la central sube", "es")
        self.assertIn("banco central", n.bigramas)
        self.assertIn("banco central sube", n.trigramas)

    def test_presencia_binaria(self):
        n = extraer("casa casa casa perro", "es")
        self.assertEqual(n.terminos, frozenset({"casa", "perro"}))
        self.assertEqual(n.trigramas,
                         frozenset({"casa casa casa", "casa casa perro"}))

    def test_idioma_sin_lista(self):
        # lang None o desconocido: stopwords = ∅ (todo ≥3 letras es término)
        n = extraer("el banco sube", None)
        self.assertEqual(n.terminos, frozenset({"banco", "sube"}))
        self.assertIn("el banco", n.bigramas)


def _stats_vector():
    """Vector §4.8: D1..D4 económicos + {playa,verano}×3 (+ singleton sol×3).
    U ordenado = [banco(3), inflacion(4), playa(3), sol(3), tipos(3), verano(3)];
    crisis df=2 fuera de U."""
    return StatsDia(
        df={"inflacion": 4, "tipos": 3, "banco": 3, "crisis": 2,
            "playa": 3, "verano": 3, "sol": 3},
        docs_elegibles=10,
        cooc={("banco", "inflacion"): 3,   # J = 3/4 = 0,75
              ("inflacion", "tipos"): 3,   # J = 3/4 = 0,75
              ("playa", "verano"): 3,      # J = 3/3 = 1,0
              ("banco", "tipos"): 2,       # c < 3 → fuera
              ("crisis", "inflacion"): 2,  # crisis fuera de U
              })


class TestClusterizarVectorCongelado(unittest.TestCase):
    def test_vector_exacto(self):
        self.assertEqual(clusterizar(_stats_vector()), [
            Cluster(miembros=("banco", "inflacion", "tipos"), etiqueta="inflacion"),
            Cluster(miembros=("playa", "verano"), etiqueta="playa"),
            Cluster(miembros=("sol",), etiqueta="sol"),
        ])

    def test_etiqueta_mayor_df_y_desempate_alfabetico(self):
        cl = clusterizar(_stats_vector())
        self.assertEqual(cl[0].etiqueta, "inflacion")  # df 4, el mayor
        self.assertEqual(cl[1].etiqueta, "playa")      # empate df 3 → alfabético

    def test_determinista(self):
        self.assertEqual(clusterizar(_stats_vector()), clusterizar(_stats_vector()))

    def test_corte_jaccard(self):
        # c=3 pero J = 3/(3+9−3) = 0,333 ≥ 0,2 → arista; J = 3/(3+30−3) = 0,1
        # < 0,2 → fuera
        st = StatsDia(df={"a": 3, "b": 9, "c": 30}, docs_elegibles=40,
                      cooc={("a", "b"): 3, ("b", "c"): 3})
        self.assertEqual(clusterizar(st), [
            Cluster(miembros=("a", "b"), etiqueta="b"),
            Cluster(miembros=("c",), etiqueta="c"),
        ])

    def test_u_df_minimo(self):
        st = StatsDia(df={"x": 2, "y": 2}, docs_elegibles=5,
                      cooc={("x", "y"): 5})
        self.assertEqual(clusterizar(st), [])  # df < 3: nadie entra en U


if __name__ == "__main__":
    unittest.main()

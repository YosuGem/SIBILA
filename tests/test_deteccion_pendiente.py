"""Tests puros de deteccion/pendiente.py: vector (d) §3.4 MK con empates,
(m1)(m2)(m3) Theil-Sen con posiciones (N5), T-B5-17 (posiciones ≠ índices),
T-B5-5 (mutaciones documentadas), T-B5-6 (Φ = math.erf)."""
import math
import unittest
from decimal import Decimal

from sibila.deteccion.pendiente import mann_kendall, theil_sen

# Vector (d): [5,5,6,7,6,8,7,9,8,10] → S=35, Var=121,0000, Z=3,0909, p=0,0010
YS_D = [5, 5, 6, 7, 6, 8, 7, 9, 8, 10]


class TestMKVectorD(unittest.TestCase):
    def test_vector_d_literal(self):
        r = mann_kendall(YS_D)
        self.assertEqual(r.s, 35)
        self.assertEqual(r.var_s, Decimal("121.0000"))
        self.assertEqual(r.z, Decimal("3.0909"))
        self.assertEqual(r.p, Decimal("0.0010"))

    def test_t_b5_5_mutaciones_documentadas(self):
        # Sin corrección de empates Var sería 125,0; sin corrección de
        # continuidad Z sería 3,1818 (recomputado: 35/√121 = 3,18181… → 4 dec
        # HALF_UP = 3,1818. NOTA: la tabla de trampas T-B5-5 del plan decía
        # "3,1820" — cifra de la TRAMPA, no vector congelado; recomputación de
        # insumos brutos demuestra 3,1818 y se corrige aquí con nota; el
        # vector (d) congelado 121,0000/3,0909 no se mueve): el test exige
        # los valores correctos 121,0000/3,0909.
        n = len(YS_D)
        var_sin_empates = n * (n - 1) * (2 * n + 5) / 18
        self.assertEqual(var_sin_empates, 125.0)
        self.assertNotEqual(mann_kendall(YS_D).var_s, Decimal("125.0000"))
        z_sin_continuidad = Decimal(str(35 / math.sqrt(121.0))).quantize(
            Decimal("0.0001"))
        self.assertEqual(z_sin_continuidad, Decimal("3.1818"))
        self.assertNotEqual(mann_kendall(YS_D).z, Decimal("3.1818"))

    def test_phi_erf(self):
        # T-B5-6: Φ(z) = 0,5·(1+erf(z/√2)) — punto de control conocido
        self.assertAlmostEqual(0.5 * (1 + math.erf(1.96 / math.sqrt(2))),
                               0.9750, places=4)
        # p del vector (d) coherente con Φ sobre su Z float interno
        z = (35 - 1) / math.sqrt(121.0)
        p = 1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))
        self.assertEqual(Decimal(str(p)).quantize(Decimal("0.0001")),
                         Decimal("0.0010"))

    def test_serie_creciente_simple(self):
        # vector de apoyo recomputado en sandbox: [1,2,3,4,5]
        r = mann_kendall([1, 2, 3, 4, 5])
        self.assertEqual(r.s, 10)
        self.assertEqual(r.var_s, Decimal("16.6667"))
        self.assertEqual(r.z, Decimal("2.2045"))
        self.assertEqual(r.p, Decimal("0.0137"))

    def test_errores(self):
        with self.assertRaises(ValueError):   # <4 puntos
            mann_kendall([1, 2, 3])
        with self.assertRaises(ValueError):   # serie constante: Var(S)=0
            mann_kendall([7.0] * 28)


class TestTheilSen(unittest.TestCase):
    def test_m1_unitario(self):
        # ys=[1,3,2,5], pos [1,2,3,4]: pendientes [−1;0,5;1;4/3;2;3] → 7/6
        self.assertEqual(theil_sen([1, 2, 3, 4], [1, 3, 2, 5]),
                         Decimal("1.1667"))

    def test_m3_serie_constante(self):
        with self.assertRaises(ValueError):
            theil_sen([1, 2, 3, 4], [5.0, 5.0, 5.0, 5.0])

    def test_t_b5_17_posiciones_no_indices(self):
        # Misma ventana con un día intermedio eliminado: con posiciones
        # reales [1,2,3,5] la pendiente es 1,6250; con índices 0..3 sería
        # 2,0000 (los pares que cruzan el hueco quedan mal escalados)
        con_pos = theil_sen([1, 2, 3, 5], [1, 2, 3, 10])
        con_idx = theil_sen([0, 1, 2, 3], [1, 2, 3, 10])
        self.assertEqual(con_pos, Decimal("1.6250"))
        self.assertEqual(con_idx, Decimal("2.0000"))
        self.assertNotEqual(con_pos, con_idx)

    def test_errores(self):
        with self.assertRaises(ValueError):
            theil_sen([1], [1.0])                  # <2 puntos
        with self.assertRaises(ValueError):
            theil_sen([1, 2], [1.0])               # longitudes distintas
        with self.assertRaises(ValueError):
            theil_sen([1, 1, 2], [1.0, 2.0, 3.0])  # posiciones no crecientes


if __name__ == "__main__":
    unittest.main()

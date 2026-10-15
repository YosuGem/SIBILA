"""Tests puros de deteccion/cusum.py: vector (c) §3.3 con día ciego (skip),
borde del cruce en float interno (T-B5-3), skip ≠ reset (T-B5-4), hueco ≠ 0
(T-B5-10/k2)."""
import unittest
from decimal import Decimal

from sibila.deteccion.cusum import ResultadoCusum, cusum

# Vector (c): u=[0,30;1,20;CIEGO;1,50;2,10;0,10;2,60;1,40;2,20;0,40] (LEY)
US_C = [0.30, 1.20, None, 1.50, 2.10, 0.10, 2.60, 1.40, 2.20, 0.40]
S_C = ["0.0000", "0.7000", "0.7000", "1.7000", "3.3000",
       "2.9000", "5.0000", "5.9000", "7.6000", "7.5000"]


class TestVectorC(unittest.TestCase):
    def test_serie_completa_valor_a_valor(self):
        # Criterio del plan: la serie S COMPLETA, no solo el cruce (reset y
        # skip dan el mismo cruce t=7 pero series distintas — T-B5-4).
        r = cusum(US_C)
        self.assertEqual(r.s, tuple(Decimal(s) for s in S_C))
        self.assertEqual(r.cruce, 6)  # primer S > 4 en el índice 6

    def test_skip_anota_s_vigente_sin_cambiar(self):
        r = cusum(US_C)
        self.assertEqual(r.s[2], r.s[1])     # día ciego: S se mantiene
        self.assertNotEqual(r.s[2], Decimal("0.0000"))  # NO es reset

    def test_k2_hueco_no_equivale_a_u_cero(self):
        # Mutación explícita (k2): u=0 daría S=S−0,5 y otra serie
        con_hueco = cusum([5.0, None, 5.0])
        con_cero = cusum([5.0, 0.0, 5.0])
        self.assertEqual(con_hueco.s, (Decimal("4.5000"), Decimal("4.5000"),
                                       Decimal("9.0000")))
        self.assertNotEqual(con_hueco.s, con_cero.s)
        self.assertEqual(con_cero.s[1], Decimal("4.0000"))


class TestBordeCruce(unittest.TestCase):
    def test_t_b5_3_cruce_en_float_no_en_decimal_mostrado(self):
        # S_float=4−ε y 4+ε se MUESTRAN igual (4,0000) pero cruzan distinto
        bajo = cusum([4.5])            # S = 4,5 − 0,5 = 4,0 exacto
        alto = cusum([4.5 + 1e-9])     # S = 4,0 + ε
        self.assertEqual(bajo.s[0], Decimal("4.0000"))
        self.assertEqual(alto.s[0], Decimal("4.0000"))
        self.assertIsNone(bajo.cruce)  # 4,0 no es > 4
        self.assertEqual(alto.cruce, 0)


class TestErrores(unittest.TestCase):
    def test_k_h_positivos(self):
        for malo in (0.0, -1.0):
            with self.assertRaises(ValueError):
                cusum([1.0], k=malo)
            with self.assertRaises(ValueError):
                cusum([1.0], h=malo)

    def test_vacia_es_valida(self):
        self.assertEqual(cusum([]), ResultadoCusum((), None))

    def test_todo_ciego_no_cruza(self):
        r = cusum([None, None, None])
        self.assertEqual(r.s, (Decimal("0.0000"),) * 3)
        self.assertIsNone(r.cruce)


if __name__ == "__main__":
    unittest.main()

"""Tests puros de deteccion/series.py: vectores (b)(j)(k1)(k3)(n)(ñ),
anti look-ahead (T-B5-7), weekday (T-B5-8), mediana par (T-B5-9)."""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from sibila.deteccion.series import (AUSENTE, Baseline, SerieDiaria,
                                     baseline_dow, elegible, es_dia_parcial,
                                     mad, mediana, serie_dia, u_t, z_r)

# Vector (b): B=[5,7,6,8,5,9,6,7], x=14 (plan_de_pruebas §3.2, LEY)
B = [5, 7, 6, 8, 5, 9, 6, 7]
BASE_B = Baseline(Decimal("6.5000"), Decimal("1.0000"), 8, False)

LUNES = date(2026, 8, 24)  # lunes conocido (T-B5-8)


def _serie(dias_vals):
    """[(date, float|None)] desde (días antes de LUNES, valor)."""
    return [(LUNES - timedelta(days=k), v) for k, v in dias_vals]


class TestMedianaMad(unittest.TestCase):
    def test_mediana_par_e_impar(self):
        self.assertEqual(mediana(B), 6.5)                 # vector (b)
        self.assertEqual(mediana([1, 2, 3, 10]), 2.5)     # T-B5-9: media de centrales
        self.assertEqual(mediana([4, 1, 7]), 4)

    def test_mad(self):
        self.assertEqual(mad(B), 1.0)                     # vector (b)
        # T-B5-9 par: desviaciones de [1,2,3,10] (med 2,5) = [0,5;0,5;1,5;7,5]
        # → mediana par (0,5+1,5)/2 = 1,0. NOTA: la primera redacción de este
        # test esperaba 1,5 — recomputado de insumos brutos, la FUNCIÓN seguía
        # el plan y el test estaba mal (corregido 2026-08-24).
        self.assertEqual(mad([1, 2, 3, 10]), 1.0)

    def test_mediana_vacia(self):
        with self.assertRaises(ValueError):
            mediana([])


class TestZrUtVectorB(unittest.TestCase):
    def test_vector_b(self):
        self.assertEqual(z_r(14.0, BASE_B), Decimal("5.0588"))
        self.assertAlmostEqual(u_t(14.0, BASE_B), 5.0587, places=4)
        # u_t es float SIN cuantizar (T-B5-2): no es un Decimal
        self.assertIsInstance(u_t(14.0, BASE_B), float)

    def test_k3_cero_real_no_es_hueco(self):
        # x=0.0 (corpus vivo, ítem ausente) NO es ciego: computable
        self.assertEqual(z_r(0.0, BASE_B), Decimal("-4.3843"))

    def test_l_recalculo(self):
        # x cambia 14 → 15 (doc tardío): z_r es función pura de (x, baseline)
        self.assertEqual(z_r(15.0, BASE_B), Decimal("5.7333"))
        # idempotencia a nivel función (TP-N8): mismos insumos, mismo valor
        self.assertEqual(z_r(14.0, BASE_B), z_r(14.0, BASE_B))

    def test_ciego_da_none(self):
        ciego = Baseline(None, None, 3, True)
        self.assertIsNone(z_r(99.0, ciego))
        self.assertIsNone(u_t(99.0, ciego))


class TestBaselineDow(unittest.TestCase):
    def _serie57(self, valores_lunes=(5.0, 7.0, 5.0, 7.0), hueco_en=None,
                 valor_otros=1.0, valor_dia=None):
        """SerieDiaria de 57 días terminada en LUNES. Los 4 lunes previos son
        las posiciones 28/35/42/49; hueco_en = cuál de ellos es None."""
        dias = tuple((LUNES - timedelta(days=56 - i)).isoformat()
                     for i in range(57))
        vals = []
        k = 0
        for i in range(57):
            d = LUNES - timedelta(days=56 - i)
            if i in (28, 35, 42, 49):
                vals.append(None if k == hueco_en else valores_lunes[k])
                k += 1
            elif i == 56 and valor_dia is not None:
                vals.append(valor_dia)
            else:
                vals.append(valor_otros)
        return SerieDiaria(dias=dias, valores=tuple(vals))

    def test_baseline_semanal(self):
        b = baseline_dow(self._serie57(), 56)
        self.assertFalse(b.ciego)
        self.assertEqual(b.n, 4)
        self.assertEqual(b.mediana, Decimal("6.0000"))   # [5,7,5,7]
        self.assertEqual(b.mad, Decimal("1.0000"))

    def test_k1_un_hueco_deja_3_obs_y_ciega(self):
        b = baseline_dow(self._serie57(hueco_en=1), 56)
        self.assertTrue(b.ciego)
        self.assertEqual(b.n, 3)
        self.assertIsNone(z_r(99.0, b))

    def test_enyee_mad_cero(self):
        # (ñ): [6,6,6,6] → mediana conservada 6,0000, mad None, ciego
        b = baseline_dow(self._serie57(valores_lunes=(6.0,) * 4), 56)
        self.assertTrue(b.ciego)
        self.assertEqual(b.mediana, Decimal("6.0000"))
        self.assertIsNone(b.mad)
        self.assertIsNone(z_r(6.0, b))
        self.assertIsNone(z_r(99.0, b))

    def test_anti_look_ahead(self):
        # T-B5-7: la fila del propio día NUNCA entra en su baseline
        b = baseline_dow(self._serie57(valor_dia=10 ** 9), 56)
        self.assertFalse(b.ciego)
        self.assertEqual(b.mediana, Decimal("6.0000"))

    def test_weekday_semantico(self):
        # T-B5-8: solo los lunes entran en la baseline del lunes; una serie
        # terminada en martes usa la celda de martes (100 en lunes, 5 si no)
        dias = tuple((LUNES - timedelta(days=56 - i)).isoformat()
                     for i in range(57))
        vals = tuple(100.0 if (LUNES - timedelta(days=56 - i)).weekday() == 0
                     else 5.0 for i in range(57))
        s = SerieDiaria(dias=dias, valores=vals)
        self.assertEqual(baseline_dow(s, 56).mediana, Decimal("100.0000"))
        dias_m = tuple((LUNES + timedelta(days=1 - 56 + i)).isoformat()
                       for i in range(57))
        vals_m = tuple(100.0 if (LUNES + timedelta(days=1 - 56 + i)
                                 ).weekday() == 0 else 5.0 for i in range(57))
        s2 = SerieDiaria(dias=dias_m, valores=vals_m)   # termina en martes
        self.assertEqual(baseline_dow(s2, 56).mediana, Decimal("5.0000"))

    def test_errores(self):
        s = self._serie57()
        with self.assertRaises(ValueError):  # índice fuera de rango
            baseline_dow(s, 57)
        with self.assertRaises(ValueError):  # no es SerieDiaria
            baseline_dow([], 0)

    def test_serie_diaria_validacion(self):
        buenos = tuple((LUNES - timedelta(days=56 - i)).isoformat()
                       for i in range(57))
        with self.assertRaises(ValueError):  # longitudes distintas
            SerieDiaria(dias=buenos, valores=(1.0,) * 56)
        with self.assertRaises(ValueError):  # != 57 posiciones
            SerieDiaria(dias=buenos[:29], valores=(1.0,) * 29)
        with self.assertRaises(ValueError):  # calendario con hueco de fecha
            mal = list(buenos)
            mal[10] = mal[11]
            SerieDiaria(dias=tuple(mal), valores=(1.0,) * 57)
        with self.assertRaises(ValueError):  # no ISO
            SerieDiaria(dias=("ayer",) * 57, valores=(1.0,) * 57)


class TestSerieDia(unittest.TestCase):
    def test_hueco_vs_ausente_vs_cero(self):
        s = [(LUNES, 0.0), (LUNES + timedelta(days=1), None)]
        self.assertEqual(serie_dia(s, LUNES), 0.0)          # 0 real
        self.assertIsNone(serie_dia(s, LUNES + timedelta(days=1)))  # hueco
        self.assertIs(serie_dia(s, LUNES + timedelta(days=2)), AUSENTE)


class TestElegibleYDiaParcial(unittest.TestCase):
    def test_n_borde_elegibilidad(self):
        # (n): media 28d 4,9999 → False; 5,0000 → True (≥ estricto)
        self.assertFalse(elegible([4.9999] * 28))
        self.assertTrue(elegible([5.0] * 28))

    def test_n_huecos_excluidos_de_la_media(self):
        # (n): 2 huecos → media sobre los 26 presentes (T-B5-16)
        self.assertTrue(elegible([5.0] * 26 + [None, None]))
        self.assertFalse(elegible([4.0] * 26 + [None, None]))

    def test_j_dia_parcial_estricto(self):
        # (j): umbral = 0,5·mediana; comparación ESTRICTA (T-B5-11)
        self.assertTrue(es_dia_parcial(99, Decimal("200")))
        self.assertFalse(es_dia_parcial(100, Decimal("200")))   # 100 !< 100
        self.assertTrue(es_dia_parcial(3, Decimal("7")))        # 3 < 3,5
        self.assertFalse(es_dia_parcial(4, Decimal("7")))


if __name__ == "__main__":
    unittest.main()

"""Vector (g)/(h)/(i) de la rampa (plan_de_pruebas §3.7/§3.8, LEY) y sus
variantes congeladas rampa_madura / rampa_sin_historia (D9), ejercitados a
través de la FACHADA motor.evaluar (contrato §3/§6) y de las primitivas.

Serie (g) — NO se inventa otra: baseline días 1-28 con patrón por weekday
L=6,M=7,X=6,J=8,V=6,S=9,D=5 + jitter [−1,+1,−1,+1] por ocurrencia; rampa
x=16 desde el día 29. Día 1 = lunes 2026-08-03. Historia "madura" = mismo
patrón extendido hacia atrás (jitter de período 4 ⇒ valor(d) = valor(d−28)).
"""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from sibila.deteccion.cusum import cusum
from sibila.deteccion.motor import evaluar
from sibila.deteccion.pendiente import mann_kendall, theil_sen
from sibila.deteccion.series import baseline_dow, u_t, z_r
from sibila.deteccion.series import SerieDiaria

DIA1 = date(2026, 8, 3)          # lunes
_BASE_W = {0: 6, 1: 7, 2: 6, 3: 8, 4: 6, 5: 9, 6: 5}
_JIT = [-1, 1, -1, 1]


def valor(d: int) -> float:
    """Patrón congelado (g); periódico cada 28 días por construcción."""
    w = (d - 1) % 7
    occ = (d - (w + 1)) // 7 + 1
    return float(_BASE_W[w] + _JIT[(occ - 1) % 4])


def x_rampa(d: int) -> float:
    return 16.0 if d >= 29 else valor(d)


def x_tranquila(d: int) -> float:
    return {29: 5.0, 30: 6.0, 31: 5.0}.get(d, valor(d))


def serie(hasta: int, xf=x_rampa, madura: bool = True) -> SerieDiaria:
    """SerieDiaria t−56…t. madura=False ⇒ historia previa al día 1 = huecos
    (None): la lectura (i) de D9."""
    lo = hasta - 56
    dias = tuple((DIA1 + timedelta(days=d - 1)).isoformat()
                 for d in range(lo, hasta + 1))
    vals = tuple(None if (not madura and d < 1) else float(xf(d))
                 for d in range(lo, hasta + 1))
    return SerieDiaria(dias=dias, valores=vals)


def us_recursion(s: SerieDiaria, t_index: int):
    """u_i de la ventana t−28…t con la baseline de SU día (D-T5-5, T-B5-1)."""
    return [None if s.valores[i] is None else u_t(s.valores[i],
                                                  baseline_dow(s, i))
            for i in range(t_index - 28, t_index + 1)]


class TestRampaMadura(unittest.TestCase):
    """(g) con historia madura: los S congelados 7,4663/13,0368/19,2817."""

    def setUp(self):
        self.s = serie(31)          # t = día 31, índice 56

    def test_zr_dias_29_30_31(self):
        for i, esperado in ((54, "6.7450"), (55, "6.0705"), (56, "6.7450")):
            with self.subTest(dia=i):
                self.assertEqual(z_r(self.s.valores[i],
                                     baseline_dow(self.s, i)),
                                 Decimal(esperado))

    def test_cusum_serie_completa(self):
        r = cusum(us_recursion(self.s, 56))
        self.assertEqual(r.s[-3:], (Decimal("7.4663"), Decimal("13.0368"),
                                    Decimal("19.2817")))
        self.assertEqual(max(r.s[:26]), Decimal("1.2214"))  # días 3-28
        self.assertEqual(r.cruce, 26)   # cruza h=4 el día 29

    def test_mk_y_theil_sen_ventana_4_31(self):
        # t−27…t: día 4 = índice 29 (la serie empieza en el día −25)
        ys = [self.s.valores[i] for i in range(29, 57)]
        mk = mann_kendall(ys)
        self.assertEqual(mk.s, 99)
        self.assertEqual(mk.var_s, Decimal("2469.0000"))
        self.assertEqual(mk.z, Decimal("1.9723"))
        self.assertEqual(mk.p, Decimal("0.0243"))
        pos = [d.toordinal() for d in self.s.fechas[29:]]
        self.assertEqual(theil_sen(pos, ys), Decimal("0.2000"))  # (m2)

    def test_t_b5_7_centinela_mk_sin_dia_actual(self):
        # Mutación de ventana (días 3-30, SIN t): p = 0,0319 ≠ 0,0243 (D-030)
        ys = [self.s.valores[i] for i in range(28, 56)]
        self.assertEqual(mann_kendall(ys).p, Decimal("0.0319"))

    def test_fachada_alerta_el_dia_31(self):
        ev = evaluar(self.s, elegible=True)
        self.assertEqual(ev.z_r, Decimal("6.7450"))
        self.assertEqual(ev.s_cusum, Decimal("19.2817"))
        self.assertEqual(ev.p_mk, Decimal("0.0243"))
        self.assertEqual(ev.pendiente, Decimal("0.2000"))
        self.assertEqual(ev.racha_z, 3)
        self.assertTrue(ev.cusum_cruza)
        self.assertTrue(ev.alerta)

    def test_no_alerta_antes_del_dia_31(self):
        ev29 = evaluar(serie(29), elegible=True)
        ev30 = evaluar(serie(30), elegible=True)
        self.assertEqual(ev29.racha_z, 1)   # racha <3 → no alerta
        self.assertEqual(ev30.racha_z, 2)
        self.assertFalse(ev29.alerta)
        self.assertFalse(ev30.alerta)

    def test_semana_tranquila_cero_alertas(self):
        s = serie(31, xf=x_tranquila)
        for i in (54, 55, 56):
            self.assertEqual(z_r(s.valores[i], baseline_dow(s, i)),
                             Decimal("-0.6745"))
        self.assertFalse(evaluar(s, elegible=True).alerta)


class TestRampaSinHistoria(unittest.TestCase):
    """(i) D9: misma rampa SIN historia previa (huecos antes del día 1):
    días 3-28 de la recursión ciegos (n<4) → skip; S cambia a los valores
    congelados 6,2449/11,8153/18,0602; cruza el día 29 igualmente."""

    def setUp(self):
        self.s = serie(31, madura=False)

    def test_dias_3_28_ciegos(self):
        us = us_recursion(self.s, 56)
        self.assertTrue(all(u is None for u in us[:26]))   # si alguien
        # "rellena" baselines, los S cambian y este test muere

    def test_cusum_sin_historia(self):
        r = cusum(us_recursion(self.s, 56))
        self.assertEqual(r.s[-3:], (Decimal("6.2449"), Decimal("11.8153"),
                                    Decimal("18.0602")))
        self.assertEqual(r.cruce, 26)
        self.assertEqual(r.s[:26], (Decimal("0.0000"),) * 26)

    def test_fachada_sin_historia(self):
        ev = evaluar(self.s, elegible=True)
        self.assertEqual(ev.z_r, Decimal("6.7450"))   # z_r y MK = (g)
        self.assertEqual(ev.p_mk, Decimal("0.0243"))
        self.assertEqual(ev.s_cusum, Decimal("18.0602"))
        self.assertEqual(ev.racha_z, 3)
        self.assertTrue(ev.alerta)


class TestAbsorcion(unittest.TestCase):
    """(h): la tensión sostenida es absorbida por la baseline rodante."""

    def test_dias_31_38_45(self):
        s = serie(45)
        esperado = {31: "6.7450", 38: "6.0705", 45: "0.6745"}
        for d, e in esperado.items():
            i = 56 - (45 - d)
            with self.subTest(dia=d):
                self.assertEqual(z_r(s.valores[i], baseline_dow(s, i)),
                                 Decimal(e))
        # día 45: absorbido (<3) → la racha muere y no hay alerta ese día
        self.assertFalse(evaluar(s, elegible=True).alerta)


if __name__ == "__main__":
    unittest.main()

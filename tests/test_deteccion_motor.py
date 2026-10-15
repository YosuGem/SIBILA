"""Tests puros de deteccion/motor.py: conjuncion (cláusulas del gate, T-B5-12,
T-B5-15, j integrado) y la fachada evaluar(SerieDiaria) -> EvalItem del
contrato §3/§6 (D-041)."""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from sibila.deteccion.motor import (EvalItem, Veredicto, conjuncion, evaluar,
                                    racha_alta)
from sibila.deteccion.series import SerieDiaria

D4 = Decimal("4")
LUNES = date(2026, 8, 24)


class TestRacha(unittest.TestCase):
    def test_t_b5_12_ciego_rompe_racha(self):
        self.assertEqual(racha_alta([D4, D4, None, D4, D4, D4]), 3)  # alerta
        self.assertEqual(racha_alta([D4, D4, D4, None, D4, D4]), 2)  # NO
        self.assertEqual(racha_alta([D4, Decimal("3"), D4, D4, D4]), 3)
        self.assertEqual(racha_alta([]), 0)
        self.assertEqual(racha_alta([None]), 0)


class TestConjuncion(unittest.TestCase):
    def test_conjunction_completa(self):
        v = conjuncion(True, [D4, D4, D4], Decimal("0.0243"), True, False)
        self.assertEqual(v, Veredicto(True, 3, "alerta"))

    def test_j_dia_parcial_manda(self):
        # (j) integrado: aunque z_r/MK/CUSUM disparan, día parcial → no alerta
        # y la capa de datos no escribe NADA del día (T-B5-19)
        v = conjuncion(True, [D4, D4, D4], Decimal("0.0243"), True, True)
        self.assertFalse(v.alerta)
        self.assertEqual(v.motivo, "dia parcial")

    def test_clausulas(self):
        casos = [
            (dict(elegible=False), "no elegible"),
            (dict(zrs=[D4, D4]), "racha insuficiente"),
            (dict(p_mk=None), "mk no computable"),      # D-T5-7
            (dict(p_mk=Decimal("0.05")), "mk no significativo"),  # T-B5-15
            (dict(p_mk=Decimal("0.99")), "mk no significativo"),
            (dict(cusum_cruce_en_racha=False), "cusum sin cruce en racha"),
        ]
        base = dict(elegible=True, zrs=[D4, D4, D4], p_mk=Decimal("0.01"),
                    cusum_cruce_en_racha=True, parcial=False)
        for sobre, motivo in casos:
            args = dict(base)
            args.update(sobre)
            with self.subTest(motivo=motivo):
                v = conjuncion(**args)
                self.assertFalse(v.alerta)
                self.assertEqual(v.motivo, motivo)

    def test_t_b5_15_p_exactamente_005_no_alerta(self):
        v = conjuncion(True, [D4] * 3, Decimal("0.0500"), True, False)
        self.assertFalse(v.alerta)


def _serie_constante(valor=10.0, rampa=False):
    """SerieDiaria 57 días terminada en LUNES; baseline estable alto."""
    dias = tuple((LUNES - timedelta(days=56 - i)).isoformat() for i in range(57))
    vals = [valor] * 57
    if rampa:
        vals[-3:] = [valor * 3] * 3   # subidón los 3 últimos días
    return SerieDiaria(dias=dias, valores=tuple(float(v) for v in vals))


class TestFachadaEvaluar(unittest.TestCase):
    def test_devuelve_evalitem_sin_status(self):
        ev = evaluar(_serie_constante(), elegible=True)
        self.assertIsInstance(ev, EvalItem)
        self.assertFalse(hasattr(ev, "status"))   # E1: status es de datos

    def test_serie_plana_no_alerta(self):
        # Baseline MAD=0 → días ciegos → z_r None, racha 0, sin alerta
        ev = evaluar(_serie_constante(), elegible=True)
        self.assertIsNone(ev.z_r)
        self.assertEqual(ev.racha_z, 0)
        self.assertFalse(ev.alerta)
        self.assertFalse(ev.cusum_cruza)

    def test_mes_sin_historia_cero_senales(self):
        # T-B5-14: arranque sin historia → 28 primeros días ciegos; la serie
        # que empieza hoy tiene los 56 días previos como huecos (None)
        dias = tuple((LUNES - timedelta(days=56 - i)).isoformat()
                     for i in range(57))
        vals = (None,) * 56 + (12.0,)
        ev = evaluar(SerieDiaria(dias=dias, valores=vals), elegible=True)
        self.assertIsNone(ev.z_r)
        self.assertEqual(ev.racha_z, 0)
        self.assertFalse(ev.alerta)
        self.assertIsNone(ev.p_mk)

    def test_ventana_mk_incompleta_da_none(self):
        # Un hueco en la ventana t−27…t → p_mk/pendiente None (D-T5-7)
        s = _serie_constante(rampa=True)
        vals = list(s.valores)
        vals[-2] = None
        ev = evaluar(SerieDiaria(dias=s.dias, valores=tuple(vals)), elegible=True)
        self.assertIsNone(ev.p_mk)
        self.assertIsNone(ev.pendiente)
        self.assertFalse(ev.alerta)

    def test_no_elegible_no_alerta(self):
        # D-042: la elegibilidad es DATO de entrada. La MISMA serie con
        # elegible=False no alerta (y con elegible=True sí: serie con rampa).
        dias = tuple((LUNES - timedelta(days=56 - i)).isoformat()
                     for i in range(57))
        vals = [6.0 + (i % 3) for i in range(52)] + [10.0, 14.0, 19.0, 26.0, 36.0]
        s = SerieDiaria(dias=dias, valores=tuple(vals))
        self.assertTrue(evaluar(s, elegible=True).alerta)
        ev = evaluar(s, elegible=False)
        self.assertFalse(ev.alerta)
        self.assertIsNotNone(ev.z_r)   # las métricas se computan igual

    def test_elegible_no_se_deriva_de_los_valores(self):  # rev. Dijkstra B1
        # Serie tipo VALENCE (∈[−1,1], media <5) con rampa: si el motor
        # calculara la elegibilidad desde los valores (la mutación), jamás
        # alertaría; como es dato de entrada, elegible=True alerta.
        dias = tuple((LUNES - timedelta(days=56 - i)).isoformat()
                     for i in range(57))
        vals = [0.6 + (i % 3) * 0.1 for i in range(52)] + [1.0, 1.4, 1.9, 2.6, 3.6]
        ev = evaluar(SerieDiaria(dias=dias, valores=tuple(vals)), elegible=True)
        self.assertTrue(ev.alerta)

    def test_campos_numericos_decimales(self):
        ev = evaluar(_serie_constante(), elegible=True)
        self.assertIsInstance(ev.z_r, (Decimal, type(None)))
        self.assertIsInstance(ev.s_cusum, (Decimal, type(None)))


if __name__ == "__main__":
    unittest.main()

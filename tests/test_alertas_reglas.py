"""Tests puros de alertas/reglas.py: vector (iii) severidades, [INMADURO]
sin escalar (T-B7-9), mapeo hex→etiqueta (T-B7-10), alertas_fmt (T-B7-13)."""
import unittest
from datetime import date
from decimal import Decimal

from sibila.alertas.reglas import (ContextoDia, Senal, alertas_fmt, clasificar,
                                   mapear_tema)

DIA = date(2026, 8, 24)


def ctx(z_r="3.4500", p_mk="0.0243", s_cusum="7.4663", racha=3,
        status="confirmado", previas=0):
    return ContextoDia(z_r=Decimal(z_r), p_mk=Decimal(p_mk) if p_mk else None,
                       s_cusum=Decimal(s_cusum) if s_cusum else None,
                       racha_z=racha, status=status,
                       alertas_previas_tema_7d=previas)


def senal(tema="terremoto", target="cluster:a1b2c3d4e5f60708", status="confirmado"):
    return Senal(tema=target, target_type="cluster", status=status, day=DIA)


class TestClasificarVectorIII(unittest.TestCase):
    def test_confirmado_zr_bajo_es_alerta(self):
        self.assertEqual(clasificar(senal(), ctx()), "alerta")

    def test_alarma_por_zr_doble(self):
        self.assertEqual(clasificar(senal(), ctx(z_r="6.7450")), "alarma")

    def test_frontera_alarma_zr_6_0000(self):  # rev. Hamilton M1 · D-T7-3
        # Umbral CONGELADO z_r ≥ 6,0000 (reglas.py): 5,9999 → alerta,
        # 6,0000 → alarma. La mutación 6→7 (o >= → >) muere aquí.
        self.assertEqual(clasificar(senal(), ctx(z_r="5.9999")), "alerta")
        self.assertEqual(clasificar(senal(), ctx(z_r="6.0000")), "alarma")
        self.assertEqual(clasificar(senal(), ctx(z_r="6.0001")), "alarma")

    def test_alarma_por_persistencia(self):
        self.assertEqual(clasificar(senal(), ctx(previas=1)), "alarma")

    def test_inmaduro_nunca_escala(self):
        # T-B7-9: z_r=6,7450 con status inmaduro → alerta, JAMÁS alarma
        self.assertEqual(clasificar(senal(status="inmaduro"),
                                    ctx(z_r="6.7450", status="inmaduro")),
                         "alerta")

    def test_tension_sin_conjuncion_es_vigilancia(self):
        self.assertEqual(clasificar(senal(), ctx(z_r="4.1000", racha=1)),
                         "vigilancia")

    def test_no_alertable(self):
        self.assertIsNone(clasificar(senal(status="reactivo"), ctx()))
        self.assertIsNone(clasificar(senal(status="descartado"), ctx()))
        self.assertIsNone(clasificar(senal(), ctx(z_r="1.0000", racha=0)))

    def test_conjuncion_exige_las_tres_patas(self):
        # racha ok pero MK sin cerrar → vigilancia, no alerta
        self.assertEqual(clasificar(senal(), ctx(p_mk="0.5000")), "vigilancia")
        # p_mk None (ventana incompleta) → vigilancia
        self.assertEqual(clasificar(senal(), ctx(p_mk=None)), "vigilancia")


class TestAlertasFmt(unittest.TestCase):
    ETIQ = {"cluster:a1b2c3d4e5f60708": "terremoto"}

    def test_linea_congelada_vector_i(self):
        s = alertas_fmt(senal(), "alerta", self.ETIQ,
                        ctx(z_r="6.7450", p_mk="0.0243", s_cusum="7.4663"))
        self.assertEqual(s, "[ALERTA] terremoto (cluster:a1b2c3d4e5f60708): "
                            "z_r 6.7450 | MK p 0.0243 | CUSUM 7.4663 (confirmado)")

    def test_marca_inmaduro(self):
        s = alertas_fmt(senal(status="inmaduro"), "alerta", self.ETIQ,
                        ctx(status="inmaduro"))
        self.assertIn("[INMADURO]", s)
        self.assertTrue(s.endswith("(inmaduro)"))

    def test_hex_sin_etiqueta_no_desaparece(self):
        txt, ok = mapear_tema("cluster:a1b2c3d4e5f60708", {})
        self.assertFalse(ok)                      # el llamador anota anomalía
        self.assertEqual(txt, "cluster:a1b2c3d4e5f60708")  # hex crudo visible

    def test_emocion(self):
        self.assertEqual(mapear_tema("emocion:es", {}), ("emocion (es)", True))

    def test_nivel_desconocido(self):
        with self.assertRaises(ValueError):
            alertas_fmt(senal(), "roja", self.ETIQ, ctx())


if __name__ == "__main__":
    unittest.main()

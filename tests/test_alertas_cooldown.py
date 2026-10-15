"""Tests puros de alertas/cooldown.py: vectores (iv)(v)(vi)(vii) — cooldown
por (tema,nivel), escalada/desescalada, borde exacto 72,000 h (T-B7-16) y
fallo-no-enfría (T-B7-15)."""
import unittest
from datetime import datetime, timedelta, timezone

from sibila.alertas.cooldown import Envio, decidir, dedup_alertas

AHORA = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)  # inyectado


def h(horas_antes: float) -> datetime:
    return AHORA - timedelta(hours=horas_antes)


class TestCooldownVectorIV(unittest.TestCase):
    def test_50h_suprime_73h_permite(self):
        hist50 = (Envio("T", "alerta", h(50)),)
        hist73 = (Envio("T", "alerta", h(73)),)
        self.assertFalse(decidir("T", "alerta", hist50, AHORA).enviar)
        self.assertEqual(decidir("T", "alerta", hist50, AHORA).motivo, "cooldown")
        self.assertTrue(decidir("T", "alerta", hist73, AHORA).enviar)

    def test_escalada_siempre_permite(self):
        # última (T, alerta) hace 1 h y llega ALARMA de T → permitida (T-B7-8)
        hist = (Envio("T", "alerta", h(1)),)
        d = decidir("T", "alarma", hist, AHORA)
        self.assertTrue(d.enviar)
        self.assertEqual(d.motivo, "escalada")

    def test_desescalada_contra_ultima_del_nivel_nuevo(self):
        # última (T, alarma) hace 30 h; llega ALERTA sin alerta previa →
        # permitida (cooldown 72 h contra la última ALERTA, no la alarma)
        hist = (Envio("T", "alarma", h(30)),)
        self.assertTrue(decidir("T", "alerta", hist, AHORA).enviar)
        # …pero si hubo una alerta hace 50 h, la alerta se suprime aunque la
        # alarma de hace 30 h sea posterior (clave = (tema, NIVEL), T-B7-7)
        hist2 = (Envio("T", "alerta", h(50)), Envio("T", "alarma", h(30)))
        self.assertFalse(decidir("T", "alerta", hist2, AHORA).enviar)

    def test_v_tema_distinto_no_interfiere(self):
        hist = (Envio("T", "alerta", h(1)),)
        self.assertTrue(decidir("OTRO", "alerta", hist, AHORA).enviar)

    def test_alarma_cooldown_24h(self):
        self.assertFalse(decidir("T", "alarma", (Envio("T", "alarma", h(20)),), AHORA).enviar)
        self.assertTrue(decidir("T", "alarma", (Envio("T", "alarma", h(25)),), AHORA).enviar)


class TestBordeExactoVectorVI(unittest.TestCase):
    ULTIMO = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)  # 72,000 h

    def test_borde_exacto_permitida(self):
        hist = (Envio("T", "alerta", self.ULTIMO),)
        self.assertTrue(decidir("T", "alerta", hist, AHORA).enviar)  # == 72 h

    def test_un_segundo_antes_suprimida(self):
        hist = (Envio("T", "alerta", self.ULTIMO + timedelta(seconds=1)),)
        self.assertFalse(decidir("T", "alerta", hist, AHORA).enviar)  # 71:59:59


class TestFalloNoEnfriaVectorVII(unittest.TestCase):
    def test_historial_filtrado_vacio_no_enfria(self):
        # Fallo total (canal='fallo:telegram'/'fallo:smtp' en alert_log) → la
        # capa los filtra → historial vacío → el reintento 1 h después EMITE
        em, sup = dedup_alertas((("T", "alerta"),), (), AHORA)
        self.assertEqual(em, (("T", "alerta"),))
        self.assertEqual(sup, ())
        self.assertEqual(decidir("T", "alerta", (), AHORA).motivo, "nueva")


class TestDedup(unittest.TestCase):
    def test_t_b7_14_orden_de_llegada_preservado(self):
        nuevas = (("zoco", "alerta"), ("alba", "alarma"), ("marea", "alerta"))
        em, _ = dedup_alertas(nuevas, (), AHORA)
        self.assertEqual(em, nuevas)   # nunca reordenado por nivel

    def test_dedup_dentro_de_la_propia_tanda(self):
        # dos alertas del MISMO tema en la tanda: la segunda ve a la primera
        em, sup = dedup_alertas((("T", "alerta"), ("T", "alerta")), (), AHORA)
        self.assertEqual(em, (("T", "alerta"),))
        self.assertEqual(sup, (("T", "alerta"),))

    def test_t_b7_17_vigilancia_sin_cooldown_individual(self):
        with self.assertRaises(ValueError):
            decidir("T", "vigilancia", (), AHORA)
        # …pero la digest la emite sin consultar historial, dos veces incluida
        em, _ = dedup_alertas((("T", "vigilancia"), ("T", "vigilancia")), (), AHORA)
        self.assertEqual(em, (("T", "vigilancia"), ("T", "vigilancia")))

    def test_nivel_desconocido(self):
        with self.assertRaises(ValueError):
            decidir("T", "roja", (), AHORA)


if __name__ == "__main__":
    unittest.main()

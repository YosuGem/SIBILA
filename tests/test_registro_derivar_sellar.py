"""Tests puros de registro: derivar (vector b, T-B6-9/10/11), formato
ventana/created_at (vector c, T-B6-7/8), vencida (vector d, T-B6-12),
construir_linea/hash_linea (T-B6-3/14)."""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from sibila.registro.derivar import (CRITERIO_ACIERTO, BorradorPrediccion,
                                     Senal, derivar)
from sibila.registro.sellar import (GENESIS, construir_linea, hash_linea,
                                    parsear_ventana, validar_created_at)
from sibila.registro.verificar import vencida

DIA = date(2026, 1, 31)


class TestDerivarVectorB(unittest.TestCase):
    def test_vector_b_solo_zr_genera(self):
        senales = (
            Senal("term", "terremoto", "z_r", Decimal("6.7450"), "confirmado", DIA),
            Senal("term", "terremoto", "cusum", Decimal("7.4663"), "confirmado", DIA),
            Senal("term", "terremoto", "mk", Decimal("0.0243"), "confirmado", DIA),
        )
        self.assertEqual(derivar(senales, DIA), (BorradorPrediccion(
            tema="terremoto", metrica="z_r", umbral="3.0000", ventana="P7D",
            criterio_acierto="z_r>3.0000 en >=1 dia de los 7 siguientes"),))

    def test_t_b6_10_criterio_literal_sin_tema_interpolado(self):
        # El criterio es la constante EXACTA para dos temas distintos
        b1 = derivar((Senal("term", "terremoto", "z_r", Decimal("4"), "confirmado", DIA),), DIA)[0]
        b2 = derivar((Senal("term", "inflación", "z_r", Decimal("4"), "confirmado", DIA),), DIA)[0]
        self.assertEqual(b1.criterio_acierto, CRITERIO_ACIERTO)
        self.assertEqual(b1.criterio_acierto, b2.criterio_acierto)
        self.assertNotIn(b1.tema, b1.criterio_acierto)

    def test_t_b6_11_orden_de_entrada_preservado(self):
        # Tres temas en orden alfabético INVERSO: la salida no se reordena
        senales = tuple(Senal("term", t, "z_r", Decimal("4"), "confirmado", DIA)
                        for t in ("zoco", "marea", "alba"))
        self.assertEqual([b.tema for b in derivar(senales, DIA)],
                         ["zoco", "marea", "alba"])

    def test_inmaduro_tambien_deriva(self):
        s = (Senal("cluster", "cluster:abc123", "z_r", Decimal("5"), "inmaduro", DIA),)
        self.assertEqual(len(derivar(s, DIA)), 1)

    def test_errores_visibles(self):
        base = dict(target_type="term", target="tema", metric="z_r",
                    score=Decimal("1"), status="confirmado", day=DIA)
        for malo in (dict(base, metric="foo"), dict(base, status="descartado"),
                     dict(base, target=""), dict(base, score=1.0)):
            with self.assertRaises(ValueError, msg=str(malo)):
                derivar((Senal(**malo),), DIA)


class TestFormatoVectorC(unittest.TestCase):
    def test_ventanas_validas(self):
        self.assertEqual(parsear_ventana("P7D"), timedelta(days=7))
        self.assertEqual(parsear_ventana("P2W"), timedelta(weeks=2))
        self.assertEqual(parsear_ventana("P1D"), timedelta(days=1))

    def test_ventanas_invalidas(self):
        # Vector (c), caso a caso (T-B6-7): incluye "P07D" (rev. cruzada N1)
        for mala in ("7 días", "P0D", "PT1H", "P7d", "P07D", "", "P1M", 7, None):
            with self.assertRaises(ValueError, msg=repr(mala)):
                parsear_ventana(mala)

    def test_created_at_valido(self):
        validar_created_at("2026-01-01T00:00:00Z")
        validar_created_at("2024-02-29T23:59:59Z")   # bisiesto real

    def test_created_at_invalido(self):
        # (c) + T-B6-8: "2026-13-01" pasa el regex pero no la fecha real
        for malo in ("2026-1-1T00:00:00Z", "2026-01-01 00:00:00",
                     "2026-13-01T00:00:00Z", "2026-01-32T00:00:00Z",
                     "2026-01-01T25:00:00Z", "2026-01-01", 0, None):
            with self.assertRaises(ValueError, msg=repr(malo)):
                validar_created_at(malo)


class TestVencidaVectorD(unittest.TestCase):
    def test_vector_d_estricto(self):
        # created 2026-01-01 + P7D: vencida el 09 (True), NO el 08 (T-B6-12)
        c = "2026-01-01T00:00:00Z"
        self.assertFalse(vencida(c, "P7D", date(2026, 1, 8)))
        self.assertTrue(vencida(c, "P7D", date(2026, 1, 9)))
        self.assertFalse(vencida(c, "P7D", date(2026, 1, 1)))
        self.assertTrue(vencida(c, "P2W", date(2026, 1, 16)))

    def test_test_cruzado_dedup(self):
        # Regla mía usada por la dedup de datos: pendiente NO vencida tapona,
        # vencida no (ratificación Orquestador sobre B1-Liskov)
        c = "2026-01-01T00:00:00Z"
        self.assertFalse(vencida(c, "P7D", date(2026, 1, 5)))   # tapona
        self.assertTrue(vencida(c, "P7D", date(2026, 1, 20)))   # no tapona


class TestConstruirLinea(unittest.TestCase):
    B = BorradorPrediccion(tema="terremoto", metrica="z_r", umbral="3.0000",
                           ventana="P7D", criterio_acierto=CRITERIO_ACIERTO)

    def test_linea_valida(self):
        l = construir_linea(self.B, "2026-01-02T00:00:00Z", GENESIS)
        self.assertEqual(len(l), 8)
        self.assertEqual(l["hash"],
                         hash_linea({k: l[k] for k in l if k != "hash"}))

    def test_validaciones(self):
        with self.assertRaises(ValueError):   # ventana
            construir_linea(BorradorPrediccion("t", "z_r", "3.0000", "P0D", "c"),
                            "2026-01-02T00:00:00Z", GENESIS)
        with self.assertRaises(ValueError):   # metrica fuera de dominio
            construir_linea(BorradorPrediccion("t", "foo", "3.0000", "P7D", "c"),
                            "2026-01-02T00:00:00Z", GENESIS)
        with self.assertRaises(ValueError):   # umbral float (T-B6-3)
            construir_linea(BorradorPrediccion("t", "z_r", 3.0, "P7D", "c"),
                            "2026-01-02T00:00:00Z", GENESIS)
        with self.assertRaises(ValueError):   # prev_hash mal formado
            construir_linea(self.B, "2026-01-02T00:00:00Z", "0" * 63)
        with self.assertRaises(ValueError):   # created_at mal formado
            construir_linea(self.B, "2026-13-01T00:00:00Z", GENESIS)

    def test_t_b6_3_float_cambia_hash_y_se_rechaza(self):
        # umbral=3.0 (float) cambiaría el hash; hash_linea lo rechaza
        l = dict(tema="t", metrica="z_r", umbral=3.0, ventana="P7D",
                 criterio_acierto="c", created_at="2026-01-02T00:00:00Z",
                 prev_hash=GENESIS)
        with self.assertRaises(ValueError):
            hash_linea(l)

    def test_t_b6_14_claves_exactas(self):
        l = dict(tema="t", metrica="z_r", umbral="3.0000", ventana="P7D",
                 criterio_acierto="c", created_at="2026-01-02T00:00:00Z",
                 prev_hash=GENESIS)
        with self.assertRaises(ValueError):   # con hash ya puesto
            hash_linea(dict(l, hash="0" * 64))
        with self.assertRaises(ValueError):   # clave ausente
            hash_linea({k: v for k, v in l.items() if k != "tema"})
        with self.assertRaises(ValueError):   # clave extra
            hash_linea(dict(l, extra="x"))


if __name__ == "__main__":
    unittest.main()

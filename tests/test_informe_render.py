"""Tests puros de informe/render.py: vector (i) byte-exacto (doble ancla:
literal + SHA-256), (ii) día hueco/mes inmaduro con las 7 secciones,
ordenación del render (T-B7-1), ASCII estructural (T-B7-3), GDELT n/d
(T-B7-5), denominadores (T-B7-11), TP-N4 doble ejecución."""
import hashlib
import unittest

from sibila.informe.render import DatosInforme, render_informe

LITERAL_I = (
    "[OK] informe: dia 2026-08-23\n"
    "== Resumen ==\n"
    "documentos: 512 (fuentes activas: 3/4)\n"
    "duplicados: 21 | excluidos por fecha: 2\n"
    "items elegibles: 17 | items ciegos: 2\n"
    "dia parcial: no | dia hueco: no | mes inmaduro: si\n"
    "== Tension ==\n"
    "sube: terremoto (z_r 6.7450)\n"
    "baja: inflacion (z_r -4.3843)\n"
    "== Emergentes ==\n"
    "- reptil gigante\n"
    "== Alertas ==\n"
    "[ALERTA] terremoto (cluster:a1b2c3d4e5f60708): z_r 6.7450 | MK p 0.0243 | CUSUM 7.4663 (confirmado)\n"
    "== Anomalias ==\n"
    "(ninguna)\n"
    "== Predicciones ==\n"
    "pendientes: 5 (inmaduras: 5) | resueltas: 0\n"
    "cobertura GDELT: n/d\n"
    "== Exportacion ==\n"
    "CSV: informe_2026-08-23.csv | JSON: informe_2026-08-23.json\n"
)
SHA_I = "f706081afb21bbc789d302a5dd095d3fbaf78bdeac9ccd5a695505e139673bb2"

ALERTA_I = ("[ALERTA] terremoto (cluster:a1b2c3d4e5f60708): z_r 6.7450 | "
            "MK p 0.0243 | CUSUM 7.4663 (confirmado)")


def datos_i(**kw):
    base = dict(dia="2026-08-23", docs=512, fuentes_on=3, fuentes_total=4,
                dups=21, excl_fecha=2, elegibles=17, ciegos=2, parcial=False,
                hueco=False, inmaduro=True, sube=(("terremoto", "6.7450"),),
                baja=(("inflacion", "-4.3843"),), emergentes=("reptil gigante",),
                alertas=(ALERTA_I,), anomalias=(), pend=5, pend_inm=5,
                resueltas=0, gdelt="n/d")
    base.update(kw)
    return DatosInforme(**base)


class TestVectorI(unittest.TestCase):
    def test_literal_byte_exacto(self):
        self.assertEqual(render_informe(datos_i()), LITERAL_I)

    def test_sha256_doble_ancla(self):
        b = render_informe(datos_i()).encode("utf-8")
        self.assertEqual(len(b), 620)
        self.assertEqual(hashlib.sha256(b).hexdigest(), SHA_I)

    def test_t_b7_1_el_render_ordena(self):
        # Entrada desordenada: misma salida byte-exacta
        d = datos_i(sube=(("b-tema", "4.0000"), ("a-tema", "9.0000")),
                    emergentes=("zeta", "alfa"))
        s = render_informe(d)
        self.assertLess(s.index("a-tema"), s.index("b-tema"))  # |z| desc
        self.assertLess(s.index("- alfa"), s.index("- zeta"))  # texto ASC

    def test_t_b7_12_doble_ejecucion_identica(self):
        self.assertEqual(render_informe(datos_i()), render_informe(datos_i()))

    def test_un_solo_newline_final_y_sin_blancas_interiores(self):
        s = render_informe(datos_i())
        self.assertTrue(s.endswith("\n") and not s.endswith("\n\n"))
        self.assertNotIn("\n\n", s)


class TestVectorIIHueco(unittest.TestCase):
    def test_hueco_estructura_completa(self):
        d = datos_i(docs=0, fuentes_on=0, hueco=True, sube=(), baja=(),
                    emergentes=(), alertas=(), pend=0, pend_inm=0,
                    anomalias=("dia hueco: 0 documentos",))
        s = render_informe(d)
        for cab in ("== Resumen ==", "== Tension ==", "== Emergentes ==",
                    "== Alertas ==", "== Anomalias ==", "== Predicciones ==",
                    "== Exportacion =="):
            self.assertIn(cab, s)          # T-B7-4: las 7 SIEMPRE
        self.assertIn("dia hueco: 0 documentos", s)
        self.assertIn("(sin variaciones)", s)
        self.assertIn("(ninguno)", s)
        self.assertIn("(ninguna)", s)
        self.assertIn("dia parcial: no | dia hueco: si | mes inmaduro: si", s)
        self.assertIn("documentos: 0 (fuentes activas: 0/4)", s)


class TestFormato(unittest.TestCase):
    def test_t_b7_3_estructura_ascii_puro(self):
        d = datos_i(sube=(), baja=(), emergentes=(), alertas=(), anomalias=())
        s = render_informe(d)
        for linea in s.splitlines():
            if not linea.startswith("- ") and "(" not in linea:
                self.assertTrue(linea.isascii(), linea)
        self.assertNotIn("·", s)

    def test_t_b7_5_gdelt_nd_literal(self):
        self.assertIn("cobertura GDELT: n/d", render_informe(datos_i()))

    def test_t_b7_10_hex_sin_etiqueta_visible_y_anotado(self):
        d = datos_i(sube=(("cluster:a1b2c3d4e5f60708", "6.7450"),))
        s = render_informe(d)
        self.assertIn("sube: cluster:a1b2c3d4e5f60708 (z_r 6.7450)", s)
        self.assertIn("cluster sin etiqueta: cluster:a1b2c3d4e5f60708", s)

    def test_t_b7_13_linea_compartida_alerta_informe(self):
        # La línea de la sección Alertas ES la salida de alertas_fmt
        from sibila.alertas.reglas import ContextoDia, Senal, alertas_fmt
        from datetime import date
        from decimal import Decimal
        c = ContextoDia(z_r=Decimal("6.7450"), p_mk=Decimal("0.0243"),
                        s_cusum=Decimal("7.4663"), racha_z=3,
                        status="confirmado", alertas_previas_tema_7d=0)
        s = Senal(tema="cluster:a1b2c3d4e5f60708", target_type="cluster",
                  status="confirmado", day=date(2026, 8, 23))
        linea = alertas_fmt(s, "alerta",
                            {"cluster:a1b2c3d4e5f60708": "terremoto"}, c)
        self.assertEqual(linea, ALERTA_I)
        self.assertIn(linea, render_informe(datos_i()))

    def test_orden_alertas_por_nivel(self):
        d = datos_i(alertas=("[VIGILANCIA] a", "[ALARMA] b", "[ALERTA] c"))
        s = render_informe(d)
        self.assertLess(s.index("[ALARMA] b"), s.index("[ALERTA] c"))
        self.assertLess(s.index("[ALERTA] c"), s.index("[VIGILANCIA] a"))

    def test_campos_obligatorios(self):
        with self.assertRaises(ValueError):
            render_informe(datos_i(dia=None))
        with self.assertRaises(ValueError):
            render_informe(datos_i(sube=None))


if __name__ == "__main__":
    unittest.main()

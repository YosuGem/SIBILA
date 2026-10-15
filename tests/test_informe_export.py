"""Tests de la exportación CSV/JSON pura (corrección de contrato §5-Liskov:
render_csv/render_json estaban prometidos y el CLI los ofrecía ya; la primera
entrega los omitió — registrado como corrección en render.py).

Vectores de juguete CONGELADOS: literal + SHA-256 (doble ancla, espejo del
vector (i) del md). Recomputados de insumos brutos antes de fijarse (D-030).
"""
import csv
import hashlib
import io
import json
import unittest

from sibila.informe.render import DatosInforme, render_csv, render_json

# Helpers duplicados (el guardián CONGELADO de test_empaquetado prohíbe
# imports entre módulos de test: solo stdlib + sibila/feedparser/requests).
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

CSV_I = (
    "seccion,clave,valor\r\n"
    "resumen,documentos,512\r\n"
    "resumen,fuentes_activas,3/4\r\n"
    "resumen,duplicados,21\r\n"
    "resumen,excluidos_por_fecha,2\r\n"
    "resumen,items_elegibles,17\r\n"
    "resumen,items_ciegos,2\r\n"
    "resumen,dia_parcial,no\r\n"
    "resumen,dia_hueco,no\r\n"
    "resumen,mes_inmaduro,si\r\n"
    "tension_sube,terremoto,6.7450\r\n"
    "tension_baja,inflacion,-4.3843\r\n"
    "emergentes,reptil gigante,\r\n"
    "alertas,," + ALERTA_I + "\r\n"
    "predicciones,pendientes,5\r\n"
    "predicciones,inmaduras,5\r\n"
    "predicciones,resueltas,0\r\n"
    "predicciones,cobertura_gdelt,n/d\r\n"
    "meta,version,informe-1\r\n"
)
SHA_CSV = "beb32a52eb0b0cc00eaa19d0dd439b9e3fe0f1f2cf363f168e71704b5855beac"
SHA_JSON = "13a45d3e202d972dc985e7a74c537bd1c8e0d3601a941728ea2a92a198f4eefb"


class TestVectorCsv(unittest.TestCase):
    def test_literal_byte_exacto(self):
        self.assertEqual(render_csv(datos_i()), CSV_I)

    def test_sha256_doble_ancla(self):
        b = render_csv(datos_i()).encode("utf-8")
        self.assertEqual(len(b), 589)
        self.assertEqual(hashlib.sha256(b).hexdigest(), SHA_CSV)

    def test_crlf_siempre(self):
        s = render_csv(datos_i())
        self.assertIn("\r\n", s)
        self.assertNotIn("\n", s.replace("\r\n", ""))   # cero LF desnudos

    def test_parseable_por_csv_stdlib(self):
        filas = list(csv.reader(io.StringIO(render_csv(datos_i()))))
        self.assertEqual(filas[0], ["seccion", "clave", "valor"])
        self.assertEqual(len(filas), 19)

    def test_orden_como_el_md(self):
        d = datos_i(sube=(("b-tema", "4.0000"), ("a-tema", "9.0000")))
        s = render_csv(d)
        self.assertLess(s.index("a-tema"), s.index("b-tema"))   # |z| desc


class TestVectorJson(unittest.TestCase):
    def test_sha256_doble_ancla(self):
        b = render_json(datos_i())
        self.assertIsInstance(b, bytes)
        self.assertEqual(len(b), 551)
        self.assertEqual(hashlib.sha256(b).hexdigest(), SHA_JSON)

    def test_determinista_y_parseable(self):
        d = json.loads(render_json(datos_i()).decode("utf-8"))
        self.assertEqual(d["dia"], "2026-08-23")
        self.assertEqual(d["predicciones"]["cobertura_gdelt"], "n/d")  # n/d jamás 0
        self.assertEqual(d["tension"]["sube"], [["terremoto", "6.7450"]])
        self.assertEqual(render_json(datos_i()), render_json(datos_i()))

    def test_canonico_claves_ordenadas(self):
        txt = render_json(datos_i()).decode("utf-8")
        self.assertNotIn('": ', txt)          # separadores compactos
        self.assertLess(txt.index('"alertas"'), txt.index('"dia"'))  # sort_keys


class TestMapeoExport(unittest.TestCase):
    def test_hex_sin_etiqueta_visible_y_anotado(self):
        d = datos_i(sube=(("cluster:a1b2c3d4e5f60708", "6.7450"),))
        j = json.loads(render_json(d).decode("utf-8"))
        self.assertEqual(j["tension"]["sube"][0][0], "cluster:a1b2c3d4e5f60708")
        self.assertIn("cluster sin etiqueta: cluster:a1b2c3d4e5f60708",
                      j["anomalias"])

    def test_vacio_sin_filas_de_lista(self):
        d = datos_i(sube=(), baja=(), emergentes=(), alertas=(), anomalias=())
        s = render_csv(d)
        self.assertNotIn("tension_sube", s)
        self.assertIn("predicciones,cobertura_gdelt,n/d", s)


if __name__ == "__main__":
    unittest.main()

"""Tests puros de registro: vector (a) TP-N13, mini-cadena h1→h2→h3 (§4.2),
roturas (e1)-(e4) en orden (T-B6-4/5/6/14), canonical_json (T-B6-1/2)."""
import hashlib
import unittest

from sibila.registro.canonico import canonical_json
from sibila.registro.sellar import GENESIS, hash_linea
from sibila.registro.verificar import verificar_lineas

# Vector (a): entrada de 7 campos (plan_de_pruebas §3.1, LEY)
ENTRADA_A = {"created_at": "2026-01-01T00:00:00Z",
             "criterio_acierto": "eco>=0,6",
             "metrica": "z_r",
             "prev_hash": "0" * 64,
             "tema": "régimen",
             "umbral": "2.50",
             "ventana": "P7D"}
SHA_A = "271a7861dc20c7d1454a0db7609c15dffce043539f0f28aceb4732990b3c427a"

# Mini-cadena §4.2 (hashes congelados, recomputados desde literales)
H2 = "6f43ab309f8d914ca1f3c42d618ed860b64c85c22e35702d0870624819985a57"
H3 = "378b52ccd1dd3e2cd5133d040b4b844d6d9b2c69aee4fbb8de1629d6d8516552"
CRITERIO_ZR = "z_r>3.0000 en >=1 dia de los 7 siguientes"


def _mini_cadena():
    """Las 3 líneas congeladas §4.2, construidas desde literales y con hash
    recomputado (nunca se confía en un hash sin recomputar, D-030)."""
    l1 = dict(ENTRADA_A)
    l1["hash"] = hash_linea(l1)
    assert l1["hash"] == SHA_A                    # génesis = vector (a)
    l2 = {"created_at": "2026-01-02T00:00:00Z", "criterio_acierto": CRITERIO_ZR,
          "metrica": "z_r", "prev_hash": l1["hash"], "tema": "terremoto",
          "umbral": "3.0000", "ventana": "P7D"}
    l2["hash"] = hash_linea(l2)
    assert l2["hash"] == H2
    l3 = {"created_at": "2026-01-03T00:00:00Z", "criterio_acierto": CRITERIO_ZR,
          "metrica": "z_r", "prev_hash": l2["hash"], "tema": "réptil gigante",
          "umbral": "3.0000", "ventana": "P7D"}
    l3["hash"] = hash_linea(l3)
    assert l3["hash"] == H3
    return (l1, l2, l3)


class TestCanonicalJsonVectorA(unittest.TestCase):
    def test_vector_a_exacto(self):
        self.assertEqual(hashlib.sha256(canonical_json(ENTRADA_A)).hexdigest(),
                         SHA_A)

    def test_t_b6_1_variantes_canonicas_mueren(self):
        # ensure_ascii por defecto o separadores con espacio → otro hash
        import json
        v1 = json.dumps(ENTRADA_A, sort_keys=True,
                        separators=(",", ":")).encode("utf-8")
        v2 = json.dumps(ENTRADA_A, sort_keys=True,
                        ensure_ascii=False).encode("utf-8")
        for variante in (v1, v2):
            self.assertNotEqual(
                hashlib.sha256(variante).hexdigest(), SHA_A)

    def test_t_b6_2_repr_no_es_canonico(self):
        self.assertNotEqual(
            hashlib.sha256(repr(ENTRADA_A).encode("utf-8")).hexdigest(), SHA_A)


class TestMiniCadena(unittest.TestCase):
    def test_cadena_completa_hash_a_hash(self):
        l1, l2, l3 = _mini_cadena()          # asserts internos: h1/h2/h3
        self.assertEqual(l1["hash"], SHA_A)
        self.assertEqual(l2["hash"], H2)
        self.assertEqual(l3["hash"], H3)

    def test_verificacion_integra(self):
        r = verificar_lineas(_mini_cadena())
        self.assertTrue(r.ok)
        self.assertEqual(r.n_lineas, 3)
        self.assertEqual(r.roturas, ())
        self.assertEqual(r.anclajes, ())

    def test_registro_vacio_es_integro(self):
        self.assertEqual(verificar_lineas(()).ok, True)
        self.assertEqual(verificar_lineas(()).n_lineas, 0)


class TestRoturas(unittest.TestCase):
    def test_e1_edicion_tema_doble_deteccion_en_orden(self):
        l1, l2, l3 = [dict(x) for x in _mini_cadena()]
        l2["tema"] = "terremotos"            # edición sin recomputar hash
        r = verificar_lineas((l1, l2, l3))
        self.assertFalse(r.ok)
        self.assertEqual(r.roturas, ("hash línea 2", "prev_hash línea 3"))

    def test_e2_permutacion(self):
        l1, l2, l3 = _mini_cadena()
        r = verificar_lineas((l1, l3, l2))
        self.assertFalse(r.ok)
        # Permutar 2↔3: la 2 (vieja 3) apunta a H2≠recomp(l1); la 3 (vieja 2)
        # apunta a H1≠recomp(vieja 3) y su created_at (01-02) DECRECE
        self.assertEqual(r.roturas, ("prev_hash línea 2", "prev_hash línea 3",
                                     "orden línea 3"))

    def test_e3_genesis_falso(self):
        l1, l2, l3 = _mini_cadena()
        l1 = dict(l1, prev_hash="1" * 64)
        r = verificar_lineas((l1, l2, l3))
        self.assertFalse(r.ok)
        self.assertIn("génesis", r.roturas)
        self.assertIn("hash línea 1", r.roturas)   # el hash ya no recomputa

    def test_e4_clave_extra_es_dominio(self):
        l1, l2, l3 = _mini_cadena()
        l2 = dict(l2, nota="metida a mano")
        r = verificar_lineas((l1, l2, l3))
        self.assertFalse(r.ok)
        self.assertEqual(r.roturas, ("dominio línea 2",))


if __name__ == "__main__":
    unittest.main()

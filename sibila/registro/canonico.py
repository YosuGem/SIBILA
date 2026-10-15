"""canonical_json — CONGELADO (spec §4.3, vector (a) TP-N13, no se negocia).

Regla 2 del plan_de_pruebas: SHA-256 sobre BYTES UTF-8 de la serialización
canónica, nunca sobre str ni repr (T-B6-2). Cualquier variante (ensure_ascii
por defecto, separadores con espacio) cambia el hash — T-B6-1; los acentos de
"régimen"/"réptil gigante" son el canario.
"""
import json


def canonical_json(obj) -> bytes:
    """Serialización canónica: claves ordenadas, separadores `,`/`:`,
    UTF-8 sin escapar no-ASCII. Devuelve bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")

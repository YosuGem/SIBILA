"""Guardia del catálogo de reloj (C-T1-6, plan T1 §2): ninguna lectura de
reloj nueva fuera de los 21 puntos catalogados. Implantación AST (no grep
de texto: los comentarios/docstrings no cuentan — lección C-B5/C-B6).

Catálogo CONGELADO por archivo (conteo de llamadas a reloj):
  alerta.py 4 · anclaje.py 1 · cli.py 2 · db.py 1 (la propia now_iso) ·
  detecta.py 2 · gdelt.py 1 · informe_datos.py 1 · ingesta.py 1 ·
  procesa.py 3 · sella.py 2                                  TOTAL = 19
Los paquetes puros (deteccion/procesado/registro/alertas/informe) tienen sus
propios guardianes y aquí deben dar CERO.

MED-1 resuelta (D-077): los 4 `date.today()` locales del CLI (R1-R4) se
sustituyeron por `_hoy_utc()`, que deriva de db.now_iso() — el mismo reloj
UTC que el sellado. El test de frontera de abajo fija el instante UTC,
simula una TZ local en el día anterior y exige que el rango por defecto
siga siendo el día UTC.

Limitación registrada (rev. Hamilton M1): la guardia cuenta llamadas con
atributo/nombre literal (now/today/utcnow/now_iso); un alias deliberado
(`_t = date.today; _t()`) o `getattr(datetime, 'now')()` la evade. Sirve
contra DESCUIDOS, no contra un adversario — limitación en equipo/MEJORAS.md.
"""
import ast
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "sibila"

# (archivo relativo a sibila/, nº de llamadas de reloj permitidas)
CATALOGO = {
    "alerta.py": 4,          # ahora por defecto ×2, ventana cooldown, digest
    "anclaje.py": 1,         # sello temporal del anclaje ots
    "paquete.py": 1,        # T2: generar(ahora=None) → reloj real solo en default
    "cli.py": 2,             # _hoy_utc (vía db.now_iso, MED-1 resuelta D-077)
                             # + R21: _ahora_defecto_cli (comando `corre`)
    "db.py": 1,              # definición de now_iso() (el único now() real)
    "detecta.py": 2,         # ahora_txt fallback + día evaluado
    "gdelt.py": 1,           # ventana de consulta GDELT
    "informe_datos.py": 1,   # período del informe (semana ISO de ayer)
    "ingesta.py": 1,         # fetched_at del documento
    "procesa.py": 3,         # hoy=None→reloj, ventana MinHash, día hábil
    "sella.py": 2,           # created_at de línea + día de señales
}

_RELOJ_ATTR = {"now", "today", "utcnow", "now_iso"}
_RELOJ_NOMBRE = {"now_iso"}


def _lecturas_reloj():
    """{archivo: nº de llamadas a reloj} por AST (llamadas reales, no texto)."""
    hits = {}
    for py in sorted(RAIZ.rglob("*.py")):
        arbol = ast.parse(py.read_text(encoding="utf-8"))
        n = 0
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call):
                f = nodo.func
                if isinstance(f, ast.Attribute) and f.attr in _RELOJ_ATTR:
                    n += 1
                elif isinstance(f, ast.Name) and f.id in _RELOJ_NOMBRE:
                    n += 1
        if n:
            hits[str(py.relative_to(RAIZ))] = n
    return hits


class TestCatalogoReloj(unittest.TestCase):
    def test_solo_los_21_puntos_catalogados(self):
        self.assertEqual(_lecturas_reloj(), CATALOGO)

    def test_total_20(self):
        self.assertEqual(sum(CATALOGO.values()), 19)  # 18 + paquete.py (T2)

    def test_paquetes_puros_cero_reloj(self):
        for paq in ("deteccion", "procesado", "registro", "alertas",
                    "informe"):
            for py in sorted((RAIZ / paq).rglob("*.py")):
                arbol = ast.parse(py.read_text(encoding="utf-8"))
                for nodo in ast.walk(arbol):
                    if isinstance(nodo, ast.Call):
                        f = nodo.func
                        if isinstance(f, ast.Attribute):
                            self.assertNotIn(f.attr, _RELOJ_ATTR,
                                             f"{py.name}: reloj .{f.attr}()")
                        elif isinstance(f, ast.Name):
                            self.assertNotIn(f.id, _RELOJ_NOMBRE,
                                             f"{py.name}: reloj {f.id}()")


class TestFronteraMed1(unittest.TestCase):
    """MED-1 (D-077): con el instante UTC fijado y la TZ local en OTRO día,
    el rango por defecto del CLI debe ser ayer UTC, nunca ayer local."""

    def test_defecto_sigue_utc_aunque_la_fecha_local_sea_otra(self):
        import os, time
        from unittest import mock
        from sibila import cli
        # UTC: 2026-10-13 00:37 → en America/New_York aún es 2026-10-12
        with mock.patch.object(cli.db, "now_iso",
                               return_value="2026-10-13T00:37:00Z"):
            vieja = os.environ.get("TZ")
            os.environ["TZ"] = "America/New_York"
            time.tzset()
            try:
                self.assertEqual(cli._hoy_utc().isoformat(), "2026-10-13")
                self.assertEqual(cli._validar_rango(None, None, None),
                                 ("2026-10-12", "2026-10-12"))
                # --dia explícito sigue intacto
                self.assertEqual(cli._validar_rango("2026-10-01", None, None),
                                 ("2026-10-01", "2026-10-01"))
            finally:
                if vieja is None:
                    del os.environ["TZ"]
                else:
                    os.environ["TZ"] = vieja
                time.tzset()


if __name__ == "__main__":
    unittest.main()

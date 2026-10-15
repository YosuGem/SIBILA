"""T1 · gdelt.py (subacción escritora aparte, M3; vacío = sin fila, TP-N12)."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sibila import db, gdelt

AYER = "2026-08-23"


class TestGdelt(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        self.db_path = self.tmp / "t.db"
        db.init_db(self.db_path)
        self.con = db.connect(self.db_path)
        self.addCleanup(self.con.close)
        self.cfg = SimpleNamespace(data_dir=self.tmp)

    def _filas(self):
        return self.con.execute("SELECT * FROM gdelt_ref ORDER BY tema, day").fetchall()

    def test_upsert_nuevo_y_actualizado(self):
        r = gdelt.actualizar(self.cfg, self.con, temas=["crisis"], dias=[AYER],
                             descargar=lambda t, d: [{"t": 1}] * 320)
        self.assertEqual(r["escritos"], 1)
        self.assertEqual(self._filas()[0]["n"], 320)
        r = gdelt.actualizar(self.cfg, self.con, temas=["crisis"], dias=[AYER],
                             descargar=lambda t, d: [{"t": 1}] * 310)  # UPSERT
        self.assertEqual(self._filas()[0]["n"], 310)
        self.assertEqual(len(self._filas()), 1)

    def test_vacio_es_sin_fila_nunca_cero(self):  # TP-N12 · spec §5
        r = gdelt.actualizar(self.cfg, self.con, temas=["crisis"], dias=[AYER],
                             descargar=lambda t, d: [])
        self.assertEqual(r["vacios"], 1)
        self.assertEqual(self._filas(), [])        # ausencia de fila = n/d

    def test_fallo_de_red_aislado_por_tema(self):
        def descargar(t, d):
            if t == "caida":
                raise ConnectionError("red caída")
            return [{"t": 1}] * 100
        r = gdelt.actualizar(self.cfg, self.con, temas=["caida", "sana"],
                             dias=[AYER], descargar=descargar)
        self.assertEqual((r["escritos"], r["fallos"]), (1, 1))
        self.assertEqual(len(self._filas()), 1)
        self.assertTrue(any("caida" in a for a in r["avisos"]))

    def test_reintento_dia_siguiente(self):
        # día 1: vacío (sin fila) → día 2: datos → la fila aparece (la
        # ausencia ES el estado "pendiente", no un 0 falso que lo tape)
        gdelt.actualizar(self.cfg, self.con, temas=["crisis"], dias=["2026-08-22"],
                         descargar=lambda t, d: [])
        gdelt.actualizar(self.cfg, self.con, temas=["crisis"], dias=[AYER],
                         descargar=lambda t, d: [{"t": 1}] * 50)
        self.assertEqual(len(self._filas()), 1)
        self.assertEqual(self._filas()[0]["day"], AYER)

    def test_temas_de_la_semana_desde_signals(self):
        with db.tx(self.con):
            self.con.execute("INSERT INTO terms(text, type) VALUES ('crisis', 'term')")
            tid = self.con.execute("SELECT id FROM terms").fetchone()[0]
            self.con.execute(
                "INSERT INTO signals(day, target_type, target_id, metric, score,"
                " status, created_at) VALUES (?, 'term', ?, 'z_r', 5.0,"
                " 'confirmado', ?)", (AYER, tid, f"{AYER}T00:00:00Z"))
        self.assertEqual(gdelt.temas_de_la_semana(self.con, "2026-08-17", AYER),
                         ["crisis"])


if __name__ == "__main__":
    unittest.main()

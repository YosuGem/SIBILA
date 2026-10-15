"""T2 §6.1 · informe json/csv desde CLI con vectores congelados literal.

Los vectores (CSV beb32a52…, JSON 13a45d3e…, md f706081a…) son LEY y se
usan como literales — nunca se recomputan. La siembra de BD reproduce
datos_i (tests.test_informe_render) salvo `etiquetas` (el hex16 del clúster
es un prefijo SHA-256 inforjable: _etiquetas_cluster se inyecta como doble,
documentado; TODO lo demás es el pipeline real BD→extracción→render→CLI).
"""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from sibila import cli, db, informe_datos

RAIZ = Path(__file__).resolve().parent.parent
DIA = "2026-08-23"
# literales importados del test puro congelado (NUNCA reescritos a mano)
from tests.test_informe_export import SHA_CSV, SHA_JSON
BYTES_JSON, BYTES_CSV = 551, 589


def _sembrar_vector(db_path: Path, data_dir: Path):
    """BD que reproduce EXACTAMENTE datos_i (vector i) por extracción real."""
    data_dir.mkdir(parents=True, exist_ok=True)
    data_dir.joinpath("fuentes.toml").write_text(
        "\n".join(f'[f{i}]\ntipo = "rss"\nurl = "http://x/{i}"'
                  for i in range(1, 5)) + "\n", encoding="utf-8")  # 4 habilitadas
    db.init_db(db_path)
    con = db.connect(db_path)
    with db.tx(con):
        for i in (1, 2, 3):
            con.execute("INSERT INTO sources(nombre, tipo, idioma, peso)"
                        " VALUES (?, 'rss', 'es', 1.0)", (f"f{i}",))
        # 512 docs en el día (21 duplicados; excluidos van aparte, dia NULL)
        for i in range(512):
            con.execute(
                "INSERT INTO documents(source_id, url_hash, published_at,"
                " published_at_real, fetched_at, body_text, content_hash, dia,"
                " duplicate_of) VALUES (?, ?, ?, 1, ?, 'cuerpo', ?, ?, ?)",
                (1 + i % 3, f"u{i}", f"{DIA}T10:00:00Z", f"{DIA}T11:00:00Z",
                 f"h{i}", DIA, 1 if i < 21 else None))
        for i in range(2):          # excluidos por fecha (dia NULL por ley)
            con.execute(
                "INSERT INTO documents(source_id, url_hash, published_at,"
                " published_at_real, fetched_at, body_text, content_hash, dia)"
                " VALUES (1, ?, NULL, 0, ?, 'cuerpo', ?, NULL)",
                (f"ux{i}", f"{DIA}T11:00:00Z", f"hx{i}"))
        # métricas del período (ts analítico D-047): elegibles/ciegos/inmaduro
        for clave, valor in (("detecta.elegibles", 17), ("detecta.items_ciego", 2),
                             ("detecta.mes_inmaduro", 1)):
            con.execute("INSERT INTO ops_metrics(ts, clave, valor)"
                        " VALUES (?, ?, ?)", (f"{DIA}T23:59:59Z", clave, valor))
        # tensión: sube/baja del último día; rows previas fuera de rango para
        # que terremoto/inflacion NO sean emergentes (MIN(day) anterior)
        for texto, zr in (("terremoto", 6.745), ("inflacion", -4.3843)):
            con.execute("INSERT INTO terms(text, type) VALUES (?, 'term')", (texto,))
            tid = con.execute("SELECT id FROM terms WHERE text = ?", (texto,)).fetchone()[0]
            con.execute("INSERT INTO term_stats(day, term_id, docs, occ, df, z_r)"
                        " VALUES ('2026-08-16', ?, 5, 5, 5, NULL)", (tid,))
            con.execute("INSERT INTO term_stats(day, term_id, docs, occ, df, z_r)"
                        " VALUES (?, ?, 5, 5, 5, ?)", (DIA, tid, zr))
        con.execute("INSERT INTO terms(text, type) VALUES ('reptil gigante', 'term')")
        tid = con.execute("SELECT id FROM terms WHERE text = 'reptil gigante'").fetchone()[0]
        con.execute("INSERT INTO term_stats(day, term_id, docs, occ, df, z_r)"
                    " VALUES (?, ?, 5, 5, 5, NULL)", (DIA, tid))
        # la única alerta del período: el clúster del vector
        con.execute("INSERT INTO terms(text, type, cluster_key) VALUES"
                    " ('cluster:a1b2c3d4e5f60708', 'cluster', ?)",
                    ("a1b2c3d4e5f60708" * 8,))
        cid = con.execute("SELECT id FROM terms WHERE type = 'cluster'").fetchone()[0]
        for metrica, score in (("z_r", 6.745), ("cusum", 7.4663), ("mk", 0.0243)):
            con.execute(
                "INSERT INTO signals(day, target_type, target_id, metric, score,"
                " status, created_at) VALUES (?, 'cluster', ?, ?, ?, 'confirmado',"
                " ?)", (DIA, cid, metrica, score, f"{DIA}T00:00:00Z"))
        sid = con.execute("SELECT id FROM signals WHERE metric = 'z_r'").fetchone()[0]
        con.execute("INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                    " VALUES (?, 'alerta', 'telegram', ?)", (sid, f"{DIA}T06:00:00Z"))
        # tracker: 5 pendientes inmaduras, 0 resueltas
        for i in range(5):
            con.execute(
                "INSERT INTO predictions(tema, metrica, umbral, ventana,"
                " criterio_acierto, created_at, hash, prev_hash, estado, madura)"
                " VALUES (?, 'z_r', '3.0000', 'P7D', 'x', ?, ?, '00',"
                " 'pendiente', 0)", (f"tema{i}", f"{DIA}T06:00:00Z", f"h{i:02d}"))
    con.close()


class TestInformeJsonCsvCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sibila José Pérez ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "sibila.db"
        self.data_dir = self.root / "datos"
        _sembrar_vector(self.db_path, self.data_dir)
        self._env = mock.patch.dict(os.environ,
                                    {"SIBILA_DB_PATH": str(self.db_path),
                                     "SIBILA_DATA_DIR": str(self.data_dir)})
        self._env.start()
        self.addCleanup(self._env.stop)
        # hex16 del clúster = prefijo SHA-256 inforjable: la RESOLUCIÓN de la
        # etiqueta se inyecta; render/extracción/CLI son reales
        self._p = mock.patch.object(
            informe_datos, "_etiquetas_cluster",
            lambda con, desde, hasta: {"cluster:a1b2c3d4e5f60708": "terremoto"})
        self._p.start()
        self.addCleanup(self._p.stop)

    def _run(self, *argv):
        import io
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_json_salida_vector_congelado(self):     # §6.1 test 1
        ruta = self.root / "i.json"
        code, out, _ = self._run("informe", "--dia", DIA, "--formato", "json",
                                 "--salida", str(ruta))
        self.assertEqual(code, 0)
        datos = ruta.read_bytes()
        self.assertEqual(len(datos), BYTES_JSON)     # vector literal, no espejo
        self.assertEqual(hashlib.sha256(datos).hexdigest(), SHA_JSON)

    def test_csv_salida_vector_congelado_y_crlf(self):  # §6.1 tests 2-3
        ruta = self.root / "i.csv"
        code, _, _ = self._run("informe", "--dia", DIA, "--salida", str(ruta))
        self.assertEqual(code, 0)                    # extensión .csv inferida
        datos = ruta.read_bytes()
        self.assertEqual(len(datos), BYTES_CSV)
        self.assertEqual(hashlib.sha256(datos).hexdigest(), SHA_CSV)
        self.assertIn(b"\r\n", datos)                # ancla CRLF (csv.reader)
        self.assertNotIn(b"\n\n", datos)

    def test_json_inferencia_extension_identico(self):  # §6.1 test 4
        a = self.root / "a.json"
        b = self.root / "b.dat"
        self._run("informe", "--dia", DIA, "--formato", "json", "--salida", str(a))
        code, _, err = self._run("informe", "--dia", DIA, "--formato", "json",
                                 "--salida", str(b))
        self.assertEqual(code, 0)
        self.assertEqual(a.read_bytes(), b.read_bytes())   # idénticos
        # y la inferencia por extensión coincide con el flag explícito
        c = self.root / "c.json"
        self._run("informe", "--dia", DIA, "--salida", str(c))
        self.assertEqual(a.read_bytes(), c.read_bytes())

    def _subproceso(self, *argv, extra_env=None):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(RAIZ), str(RAIZ.parent / "deps")])
        env.update(extra_env or {})
        return subprocess.run([sys.executable, "-m", "sibila", *argv], env=env,
                              cwd=self.root, capture_output=True, timeout=60)

    def test_json_stdout_parseable_sin_repr(self):   # §6.1 test 2 (anti-b'...')
        r = self._subproceso("informe", "--dia", DIA, "--formato", "json")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        # stdout = JSON + línea [OK]; el payload NO es repr de bytes
        lineas = r.stdout.split(b"[OK]")
        objeto = json.loads(lineas[0])             # parsea de verdad
        self.assertEqual(objeto["version"], "informe-1")

    def test_json_stdout_cp1252_exit_0(self):        # §6.1 test 6
        r = self._subproceso("informe", "--dia", DIA, "--formato", "json",
                             extra_env={"PYTHONIOENCODING": "cp1252"})
        self.assertEqual(r.returncode, 0, r.stderr.decode())

    def test_meta_equivalente_md_y_json(self):       # §6.1 test 7
        a = self.root / "a.md"
        b = self.root / "b.json"
        self._run("informe", "--dia", DIA, "--formato", "md", "--salida", str(a))
        self._run("informe", "--dia", DIA, "--formato", "json", "--salida", str(b))
        meta_md = json.loads((self.root / "a.md.meta.json").read_text("utf-8"))
        meta_js = json.loads((self.root / "b.json.meta.json").read_text("utf-8"))
        self.assertEqual(meta_md["rango"], [DIA, DIA])
        self.assertEqual(meta_js["rango"], [DIA, DIA])
        self.assertEqual(meta_md["renderer"], meta_js["renderer"])
        self.assertEqual(meta_md["formato"], "md")
        self.assertEqual(meta_js["formato"], "json")


if __name__ == "__main__":
    unittest.main()

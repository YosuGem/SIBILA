"""T-INS-1..8 (T2 §4): instalador, requirements, secretos, descargador
(doble inyectado, SIN red real), instalación limpia en dos carriles y XML de
tareas. Todo unittest stdlib; lo pesado va por subprocess con PYTHONPATH
explícito (bootstrap honesto, D-032)."""
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPS = REPO.parent / "deps"
sys.path.insert(0, str(REPO))  # tools/ es namespace package

from tools import descargar_recursos as dr   # noqa: E402
from tools import generar_secretos as gs      # noqa: E402
from tools import preparar_tarea as pt        # noqa: E402


class TestIns1Formatos(unittest.TestCase):
    def test_bats_crlf_puro(self):
        for nombre in ("instalar.bat", "ingesta_diaria.bat",
                       "pipeline_diario.bat"):
            b = (REPO / nombre).read_bytes()
            self.assertEqual(b.count(b"\n"), b.count(b"\r\n"),
                             f"{nombre}: LF suelto (B1-Dijkstra)")

    def test_xml_utf8_sin_bom(self):
        import xml.etree.ElementTree as ET
        for nombre in ("tarea_ingesta.xml", "tarea_diaria.xml"):
            b = (REPO / nombre).read_bytes()
            self.assertFalse(b.startswith(b"\xef\xbb\xbf"), f"{nombre}: BOM")
            ET.fromstring(b.decode("utf-8"))

    def test_tarea_diaria_pt2h(self):
        txt = (REPO / "tarea_diaria.xml").read_text(encoding="utf-8")
        self.assertIn("<ExecutionTimeLimit>PT2H</ExecutionTimeLimit>", txt)
        self.assertIn("pipeline_diario.bat", txt)

    def test_pipeline_entrega_alertas(self):  # rev. Dijkstra B2 (decisión
        # del orquestador): la cadena diaria DEBE incluir `alerta enviar`
        txt = (REPO / "pipeline_diario.bat").read_text(encoding="utf-8")
        self.assertIn("-m sibila alerta enviar", txt)
        # …en la posición correcta: tras sellar/verificar el registro y antes
        # del digest semanal (la entrega no puede depender del digest)
        i_env = txt.index("-m sibila alerta enviar")
        i_sellar = txt.index("-m sibila registro sellar")
        i_dig = txt.index("-m sibila alerta digest")
        self.assertLess(i_sellar, i_env)
        self.assertLess(i_env, i_dig)

    def test_instalar_verifica_paquete_en_destino(self):  # rev. Hamilton M2
        # El manifiesto se verifica donde se usa: paso final del instalador
        txt = (REPO / "instalar.bat").read_text(encoding="utf-8")
        self.assertIn("-m sibila paquete verificar", txt)


class TestIns2Requirements(unittest.TestCase):
    NUCLEO = {"feedparser", "sgmllib3k", "requests", "fasttext-predict",
              "lingua-language-detector", "vaderSentiment"}

    def test_parsea_sin_duplicados_y_con_nucleo(self):
        pkgs = []
        for lin in (REPO / "requirements.txt").read_text().splitlines():
            lin = lin.split("#", 1)[0].strip()
            if not lin:
                continue
            self.assertRegex(lin, r"\A[A-Za-z0-9_.-]+==[A-Za-z0-9.*]+\Z", lin)
            pkgs.append(lin.split("==")[0])
        self.assertEqual(len(pkgs), len(set(pkgs)), "duplicados")
        self.assertTrue(self.NUCLEO <= set(pkgs),
                        f"faltan: {self.NUCLEO - set(pkgs)}")


class TestIns3Secretos(unittest.TestCase):
    def test_idempotente_y_toml_valido(self):
        with tempfile.TemporaryDirectory() as td:
            ruta = Path(td) / "config.local.toml"
            self.assertTrue(gs.generar_secretos(ruta))
            k1 = ruta.read_text()
            self.assertTrue(gs.generar_secretos(ruta))   # 2ª vez: NO pisa
            self.assertEqual(k1, ruta.read_text())
            d = tomllib.loads(k1)
            self.assertRegex(d["secretos"]["hmac_key"], r"\A[0-9a-f]{64}\Z")


class TestIns4DescargadorDoble(unittest.TestCase):
    def _zips(self):
        """Zips mínimos sintéticos que satisfacen los normalizadores."""
        import io, zipfile
        def _zip(archivos):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n, c in archivos.items():
                    z.writestr(n, c)
            return buf.getvalue()
        return {
            dr.URL_LID176: b"modelo-falso",
            dr.URL_VAD_V2: _zip({dr._EMO_V2_UNIGRAMS:
                                 "term\tvalence\tarousal\tdominance\n"
                                 "joy\t0.96\t0.65\t0.5\n"}),
            dr.URL_VAD_V1: _zip({"NRC-VAD-Lexicon/OneFilePerLanguage/"
                                 "Spanish-NRC-VAD-Lexicon.txt":
                                 "English Word\tValence\tArousal\tDominance\tSpanish Word\n"
                                 "joy\t0.96\t0.65\t0.50\talegría\n"}),
            dr.URL_EMO: _zip({"NRC-Emotion-Lexicon/NRC-Emotion-Lexicon-"
                              "Wordlevel-v0.92.txt":
                              "joy\tjoy\t1\njoy\tpositive\t1\n",
                              "NRC-Emotion-Lexicon/OneFilePerLanguage/"
                              "Spanish-NRC-EmoLex.txt":
                              "English Word\tanger\tanticipation\tdisgust\tfear\tjoy\tnegative\tpositive\tsadness\tsurprise\ttrust\tSpanish Word\n"
                              "joy\t0\t0\t0\t0\t1\t0\t1\t0\t0\t0\talegría\n"}),
        }

    def test_verifica_idempotente_y_rechaza_hash_malo(self):
        import sibila.procesado.emocion as emo
        with tempfile.TemporaryDirectory() as td:
            rec = Path(td) / "recursos"
            zips = self._zips()
            # 1) dict vacío → FALLO, no descarga
            real = dict(emo.SHA256_ESPERADOS)
            emo.SHA256_ESPERADOS.clear()
            try:
                self.assertEqual(dr.descargar(rec, bajador=zips.get,
                                              imprimir=lambda *a: None), 1)
                self.assertFalse(rec.exists() and any(rec.iterdir()))
            finally:
                emo.SHA256_ESPERADOS.update(real)
            # 2) hash fijado mal → FALLO, no escribe
            for k in real:
                emo.SHA256_ESPERADOS[k] = "0" * 64
            lid_real = dr.SHA256_LID176
            dr.SHA256_LID176 = "0" * 64
            try:
                self.assertEqual(dr.descargar(rec, bajador=zips.get,
                                              imprimir=lambda *a: None), 1)
                self.assertEqual(len(list(rec.iterdir())), 0)
            finally:
                emo.SHA256_ESPERADOS.update(real)
                dr.SHA256_LID176 = lid_real
            # 3) hash bueno (recomputado del doble) → escribe; 2ª vez no re-descarga
            buenos = {k: dr._sha256(dr.ESPEC[k][1](zips[dr.ESPEC[k][0]]))
                      for k in emo.SHA256_ESPERADOS}
            emo.SHA256_ESPERADOS.update(buenos)
            dr.SHA256_LID176 = dr._sha256(zips[dr.URL_LID176])
            try:
                self.assertEqual(dr.descargar(rec, bajador=zips.get,
                                              imprimir=lambda *a: None), 0)
                self.assertEqual(len(list(rec.iterdir())), 5)
                llamadas = []
                def contador(url):
                    llamadas.append(url)
                    return zips[url]
                self.assertEqual(dr.descargar(rec, bajador=contador,
                                              imprimir=lambda *a: None), 0)
                self.assertEqual(llamadas, [])   # idempotente: no re-descarga
            finally:
                emo.SHA256_ESPERADOS.update(real)
                dr.SHA256_LID176 = lid_real

    def test_presente_con_hash_malo_no_se_pisa(self):
        import sibila.procesado.emocion as emo
        with tempfile.TemporaryDirectory() as td:
            rec = Path(td) / "recursos"
            rec.mkdir(parents=True)
            zips = self._zips()
            buenos = {k: dr._sha256(dr.ESPEC[k][1](zips[dr.ESPEC[k][0]]))
                      for k in emo.SHA256_ESPERADOS}
            real = dict(emo.SHA256_ESPERADOS)
            lid_real = dr.SHA256_LID176
            emo.SHA256_ESPERADOS.update(buenos)
            dr.SHA256_LID176 = dr._sha256(zips[dr.URL_LID176])
            try:
                # fichero CORRUPTO pre-existente: FALLO y NUNCA se pisa
                (rec / "lid.176.ftz").write_bytes(b"corrupto")
                msgs = []
                rc = dr.descargar(rec, bajador=zips.get, imprimir=msgs.append)
                self.assertEqual(rc, 1)
                self.assertEqual((rec / "lid.176.ftz").read_bytes(),
                                 b"corrupto")
                self.assertTrue(any("INCORRECTO" in m for m in msgs))
            finally:
                emo.SHA256_ESPERADOS.update(real)
                dr.SHA256_LID176 = lid_real

    def test_red_caida_es_aviso_y_exit_0(self):
        def caida(url):
            raise dr.RedError("sin red")
        import sibila.procesado.emocion as emo
        with tempfile.TemporaryDirectory() as td:
            msgs = []
            self.assertEqual(dr.descargar(Path(td) / "recursos",
                                          bajador=caida,
                                          imprimir=msgs.append), 0)
            self.assertTrue(any("degradado" in m for m in msgs))


class TestIns5InstalacionLimpia(unittest.TestCase):
    """Dos carriles (D-048/H2): con deps (init+check+doctor OK) y SIN deps
    (doctor exit 1 con los FALLOs D2 exactos). Sin venv real (sin red)."""

    def _entorno(self, tmp: Path, con_deps: bool):
        env = dict(os.environ)
        env["SIBILA_DATA_DIR"] = str(tmp / "datos")
        env["SIBILA_DB_PATH"] = str(tmp / "datos" / "sibila.db")
        env["PYTHONPATH"] = os.pathsep.join(
            [str(DEPS), str(REPO)] if con_deps else [str(REPO)])
        return env

    def test_carril_con_deps(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            env = self._entorno(tmp, True)
            for cmd in (["init"], ["check"], ["doctor"]):
                r = subprocess.run([sys.executable, "-m", "sibila"] + cmd,
                                   capture_output=True, text=True, env=env,
                                   cwd=td)
                self.assertEqual(r.returncode, 0, f"{cmd}: {r.stdout}")
            self.assertIn("check: VERDE", r.stdout if False else
                          subprocess.run([sys.executable, "-m", "sibila",
                                          "check"], capture_output=True,
                                         text=True, env=env, cwd=td).stdout)
            self.assertIn("doctor: SANO", r.stdout)
            self.assertIn("modo degradado", r.stdout)  # recursos ausentes: AVISO

    def test_carril_sin_deps(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            env = self._entorno(tmp, False)
            # -I: aislado (sin PYTHONPATH ni site-packages → deps AUSENTES);
            # el repo se añade a mano dentro del wrapper para que sibila
            # sí sea importable pero feedparser/fasttext/... no.
            code = ("import sys; sys.path.insert(0, " + repr(str(REPO)) + ");"
                    " import runpy; sys.argv=['sibila','doctor'];"
                    " runpy.run_module('sibila', run_name='__main__')")
            r = subprocess.run([sys.executable, "-I", "-c", code],
                               capture_output=True, text=True, env=env, cwd=td)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            for dep in ("feedparser", "fasttext", "vaderSentiment", "sgmllib"):
                self.assertIn(f"dep NO importable: {dep}", r.stdout)


class TestIns6DoctorRutas(unittest.TestCase):
    def test_data_dir_por_entorno(self):
        # SIBILA_DATA_DIR gobierna dónde busca doctor/descargar (H3)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            env = self_env = dict(os.environ)
            env["SIBILA_DATA_DIR"] = str(tmp / "otro_sitio")
            env.pop("SIBILA_DB_PATH", None)
            env["PYTHONPATH"] = os.pathsep.join([str(DEPS), str(REPO)])
            r = subprocess.run([sys.executable, "-m", "sibila", "init"],
                               capture_output=True, text=True, env=env, cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((tmp / "otro_sitio" / "sibila.db").is_file())


class TestIns7PrepararTarea(unittest.TestCase):
    def test_sustitucion_xml_valido(self):
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as td:
            out = pt.preparar(REPO / "tarea_diaria.xml", Path(td) / "t.xml",
                              r"C:\sibila", "2026-08-26T07:45:00")
            # D-077 (prueba real W11): schtasks exige UTF-16 LE con BOM;
            # UTF-8 sin BOM era rechazado. El final debe ser UTF-16.
            crudo = out.read_bytes()
            self.assertTrue(crudo.startswith(b"\xff\xfe"),
                            "schtasks exige BOM UTF-16 LE (FF FE)")
            txt = crudo.decode("utf-16")
            self.assertIn('encoding="UTF-16"', txt)
            self.assertNotIn("{SIBILA_RAIZ}", txt)
            self.assertNotIn("{START_BOUNDARY}", txt)
            self.assertIn("C:\\sibila", txt)
            self.assertIn("2026-08-26T07:45:00", txt)
            ET.fromstring(txt)

    def test_ruta_con_ampersand_rechazada(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                pt.preparar(REPO / "tarea_ingesta.xml", Path(td) / "t.xml",
                            "C:\\R&R", "2026-08-26T07:00:00")


if __name__ == "__main__":
    unittest.main()

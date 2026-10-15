"""T1 · cli.py (9 tests, plan Liskov §2.6 + D-B1-14: parcheo solo en fronteras config/db).
Los tests usan env SIBILA_DATA_DIR/SIBILA_DB_PATH al sandbox acentuado: ejercitan la vía
env real (precedencia spec §2) sin tocar el root del repo."""
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from sibila import cli, config


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))

    def setUp(self):
        self.dir = self.tmp / self._testMethodName
        self.dir.mkdir()
        datos = self.dir / "datos"
        self.env = mock.patch.dict(os.environ, {
            "SIBILA_DATA_DIR": str(datos),
            "SIBILA_DB_PATH": str(datos / "sibila.db"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def _corre(self, argv):
        salida = io.StringIO()
        with redirect_stdout(salida):
            codigo = cli.main(argv)
        return codigo, salida.getvalue()


class TestCli(Base):
    def test_init_exit_0(self):
        codigo, out = self._corre(["init"])
        self.assertEqual(codigo, 0, out)
        self.assertTrue((self.dir / "datos" / "sibila.db").exists())

    def test_init_doble_exit_0(self):
        self._corre(["init"])
        codigo, out = self._corre(["init"])  # doble init (trampa T5)
        self.assertEqual(codigo, 0, out)

    def test_check_verde_exit_0(self):
        self._corre(["init"])
        codigo, out = self._corre(["check"])
        self.assertEqual(codigo, 0, out)
        self.assertIn("VERDE", out)

    def test_literal_12_tablas_asertado(self):  # rev. Hamilton M1 r2: cerrar la red
        """El conteo de tablas en init y check es LITERAL asertado: una mutación
        12→11 en el texto debe fallar aquí (el pecado original de B1 fue corregir
        el código sin cerrar la red de tests)."""
        codigo, out = self._corre(["init"])
        self.assertEqual(codigo, 0, out)
        self.assertIn("12 tablas", out)
        codigo, out = self._corre(["check"])
        self.assertEqual(codigo, 0, out)
        self.assertIn("12 tablas", out)
        self.assertNotIn("11 tablas", out)

    def test_check_sin_db_exit_1(self):
        codigo, out = self._corre(["check"])
        self.assertEqual(codigo, 1, out)
        self.assertIn("ROJO", out)
        self.assertIn("sibila init", out)

    def test_check_avisos_no_tumban(self):
        self._corre(["init"])
        with mock.patch("shutil.which", lambda _nombre: None):  # sin git ni ots
            codigo, out = self._corre(["check"])
        self.assertEqual(codigo, 0, out)  # anclaje 'pendiente' NO es fallo (TP-N1)
        self.assertGreaterEqual(out.count("[AVISO]"), 2)

    def test_check_config_rota_exit_1(self):
        with mock.patch("sibila.config.load_config",
                        side_effect=config.ConfigError("config inválida de prueba")):
            codigo, out = self._corre(["check"])
        self.assertEqual(codigo, 1, out)
        self.assertIn("[FALLO]", out)
        self.assertIn("config inválida de prueba", out)  # el mensaje específico (no el catch genérico — rev. Hamilton)
        self.assertNotIn("Traceback", out)

    def test_sin_stubs_todos_los_comandos_son_reales(self):
        # Bloque 7 retira los dos últimos stubs: NINGÚN subcomando queda en
        # "no implementado en este bloque".
        salida = io.StringIO()
        with redirect_stdout(salida), self.assertRaises(SystemExit):
            cli.main(["--help"])
        self.assertNotIn("no implementado en este bloque", salida.getvalue())
        for nombre in ("init", "check", "ingesta", "procesa", "detecta",
                       "registro", "informe", "alerta", "doctor", "paquete"):
            self.assertIn(nombre, salida.getvalue())

    def test_ayuda_en_espanol(self):
        salida = io.StringIO()
        with redirect_stdout(salida), self.assertRaises(SystemExit) as ctx:
            cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("base de datos", salida.getvalue())
        self.assertIn("verde/rojo", salida.getvalue())  # rev. Hamilton: aserto relajado no

    def test_comando_desconocido_exit_2(self):
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(io.StringIO()):
                cli.main(["inventado"])
        self.assertEqual(ctx.exception.code, 2)


class TestRobustez(Base):
    """Rev. bloque 1 (Dijkstra B1, Hamilton T1.6b/c + echo_flags no vacía)."""

    def test_check_config_oserror_informe_completo(self):  # rev. M7: OSError tampoco amputa
        with mock.patch("sibila.config.load_config", side_effect=OSError("es un directorio")):
            codigo, out = self._corre(["check"])
        self.assertEqual(codigo, 1, out)
        self.assertIn("[FALLO]", out)
        self.assertIn("resultado:", out)
        self.assertNotIn("Traceback", out)

    def test_check_bd_basura_exit_1_sin_traceback(self):  # T1.6b de Hopper
        datos = self.dir / "datos"
        datos.mkdir()
        (datos / "sibila.db").write_bytes(b"esto no es una base sqlite")
        codigo, out = self._corre(["check"])
        self.assertEqual(codigo, 1, out)
        self.assertIn("[FALLO]", out)
        self.assertNotIn("Traceback", out)

    def test_check_echo_flags_no_vacia_exit_1(self):
        from sibila import db
        self._corre(["init"])
        con = db.connect(self.dir / "datos" / "sibila.db")
        with db.tx(con):
            cur = con.execute("INSERT INTO documents(url_hash) VALUES ('d1')")
        with db.tx(con):
            con.execute("INSERT INTO echo_flags(doc_id, tipo, score) VALUES (?, 'meme', 0.5)",
                        (cur.lastrowid,))
        con.close()
        codigo, out = self._corre(["check"])
        self.assertEqual(codigo, 1, out)
        self.assertIn("echo_flags", out)

    def test_check_pagina_corrompida_informe_completo(self):  # rev. B1′: la CLASE entera, no solo el caso
        self._corre(["init"])
        ruta = self.dir / "datos" / "sibila.db"
        with ruta.open("r+b") as f:  # corrompe una página INTERMEDIA (distinto de fichero basura y de tabla borrada)
            f.seek(4096 * 2)
            f.write(b"\xff" * 512)
        codigo, out = self._corre(["check"])
        self.assertEqual(codigo, 1, out)
        self.assertIn("resultado:", out)   # el informe llega al resumen
        self.assertIn("ROJO", out)
        self.assertNotIn("Traceback", out)

    def test_check_tabla_borrada_informe_completo(self):  # rev. B1: el informe NO se amputa
        from sibila import db
        self._corre(["init"])
        con = db.connect(self.dir / "datos" / "sibila.db")
        con.execute("DROP TABLE echo_flags")
        con.close()
        codigo, out = self._corre(["check"])
        self.assertEqual(codigo, 1, out)
        self.assertIn("echo_flags", out)   # nombra la tabla
        self.assertIn("resultado:", out)   # informe completo hasta el final
        self.assertIn("ROJO", out)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main()

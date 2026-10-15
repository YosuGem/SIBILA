"""T1 · config.py (9 tests, plan Liskov §2.6)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sibila import config


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))

    def setUp(self):
        self.root = self.tmp / self._testMethodName
        self.root.mkdir()

    def _escribe(self, nombre, texto, bom=False):
        p = self.root / nombre
        datos = texto.encode("utf-8")
        p.write_bytes((b"\xef\xbb\xbf" + datos) if bom else datos)
        return p


class TestConfig(Base):
    def test_defaults_sin_archivos(self):
        cfg = config.load_config(root=self.root)
        self.assertEqual(cfg.data_dir, self.root / "datos")
        self.assertEqual(cfg.db_path, self.root / "datos" / "sibila.db")
        self.assertEqual(cfg.log_level, "INFO")
        self.assertTrue(any("config.toml" in a for a in cfg.avisos))

    def test_local_pisa_a_base(self):
        self._escribe("config.toml", '[general]\nlog_level = "INFO"\n')
        self._escribe("config.local.toml", '[general]\nlog_level = "DEBUG"\n')
        self.assertEqual(config.load_config(root=self.root).log_level, "DEBUG")

    def test_env_gana(self):
        self._escribe("config.toml", '[general]\nlog_level = "INFO"\n')
        self._escribe("config.local.toml", '[general]\nlog_level = "DEBUG"\n')
        with mock.patch.dict(os.environ, {"SIBILA_LOG_LEVEL": "ERROR"}):
            self.assertEqual(config.load_config(root=self.root).log_level, "ERROR")

    def test_toml_roto_mensaje_claro(self):
        self._escribe("config.toml", "[general]\nlog_level = \n")
        with self.assertRaises(config.ConfigError) as ctx:
            config.load_config(root=self.root)
        self.assertIn("config.toml", str(ctx.exception))  # nunca TOMLDecodeError cruda
        self.assertIn("line", str(ctx.exception))  # y con la línea del error (rev. Hamilton)

    def test_bom_mensaje_explicito(self):
        self._escribe("config.toml", "[general]\n", bom=True)
        with self.assertRaises(config.ConfigError) as ctx:
            config.load_config(root=self.root)
        self.assertIn("BOM", str(ctx.exception))

    def test_clave_desconocida(self):
        self._escribe("config.toml", '[general]\nlog_leve = "INFO"\n')
        with self.assertRaises(config.ConfigError) as ctx:
            config.load_config(root=self.root)
        self.assertIn("log_leve", str(ctx.exception))

    def test_tipo_incorrecto(self):
        self._escribe("config.toml", "[general]\nlog_level = 123\n")
        with self.assertRaises(config.ConfigError):
            config.load_config(root=self.root)

    def test_rutas_relativas_ancladas_al_proyecto(self):
        self._escribe("config.toml", '[general]\ndata_dir = "datos"\n')
        otro = Path(tempfile.mkdtemp(prefix="sibila cwd "))
        cwd = os.getcwd()
        try:
            os.chdir(otro)
            cfg = config.load_config(root=self.root)
        finally:
            os.chdir(cwd)
        self.assertEqual(cfg.data_dir, self.root / "datos")  # NO al cwd

    def test_secretos_fuera_del_repr(self):
        # El valor debe NO colisionar con el nombre del propio test (la ruta tmp lo contiene)
        valor = "X7q-PARAMETRO-UNICO-9z"
        self._escribe("config.local.toml", f'[secretos]\nhmac_key = "{valor}"\n')
        cfg = config.load_config(root=self.root)
        self.assertNotIn(valor, repr(cfg))
        self.assertEqual(cfg.secretos["hmac_key"], valor)


class TestReglasNuevas(Base):
    """Rev. bloque 1 (Dijkstra M5/M6)."""

    def test_secretos_prohibidos_en_config_toml(self):  # rev. M5: el archivo versionado no puede tener secretos
        self._escribe("config.toml", '[secretos]\nhmac_key = "x"\n')
        with self.assertRaises(config.ConfigError) as ctx:
            config.load_config(root=self.root)
        self.assertIn("secretos", str(ctx.exception).lower())

    def test_env_vacia_ignorada(self):  # rev. M6: "" = no definida
        with mock.patch.dict(os.environ, {"SIBILA_DATA_DIR": ""}):
            cfg = config.load_config(root=self.root)
        self.assertEqual(cfg.data_dir, self.root / "datos")


class TestClavesAlertas(Base):
    """CRIT-2: las 5 claves de alertas + bordes de smtp_puerto (rev. cruce)."""

    def test_cinco_claves_nuevas_cargan(self):
        self._escribe("config.local.toml",
                      '[secretos]\ntelegram_token = "t"\ntelegram_chat = "1"\n'
                      'smtp_password = "p"\nsmtp_host = "h"\nsmtp_puerto = 587\n'
                      'smtp_usuario = "u"\nsmtp_destino = "d"\n')
        cfg = config.load_config(root=self.root)
        for k in ("telegram_chat", "smtp_host", "smtp_usuario", "smtp_puerto",
                  "smtp_destino"):
            self.assertIn(k, cfg.secretos)

    def test_smtp_puerto_str_digitos_se_normaliza_a_int(self):
        self._escribe("config.local.toml", '[secretos]\nsmtp_puerto = "2525"\n')
        cfg = config.load_config(root=self.root)
        self.assertEqual(cfg.secretos["smtp_puerto"], 2525)
        self.assertIsInstance(cfg.secretos["smtp_puerto"], int)

    def test_smtp_puerto_bordes_rechazados(self):
        for valor in ('"quinientos"', '"-5"', "-5", "0", "99999", "587.0",
                      "true", '"²"'):
            self._escribe("config.local.toml",
                          f'[secretos]\nsmtp_puerto = {valor}\n')
            with self.assertRaises(config.ConfigError, msg=valor):
                config.load_config(root=self.root)

    def test_smtp_puerto_extremos_validos(self):
        for valor, esperado in (("1", 1), ("65535", 65535)):
            self._escribe("config.local.toml",
                          f'[secretos]\nsmtp_puerto = {valor}\n')
            cfg = config.load_config(root=self.root)
            self.assertEqual(cfg.secretos["smtp_puerto"], esperado)



if __name__ == "__main__":
    unittest.main()

"""T1 · anclaje git/ots del registro (plan §5, trampa 10). git real si existe;
PATH inyectado para el caso 'sin git'."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sibila import anclaje, db

HAY_GIT = shutil.which("git") is not None


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        self.db_path = self.tmp / "t.db"
        db.init_db(self.db_path)
        self.con = db.connect(self.db_path)
        self.addCleanup(self.con.close)
        self.cfg = SimpleNamespace(data_dir=self.tmp / "datos")
        self.reg = self.tmp / "datos" / "registro"
        self.reg.mkdir(parents=True)
        (self.reg / anclaje.FICHERO).write_bytes(
            b'{"tema":"crisis","hash":"ab12"}\n')


class TestAnclajeSinGit(Base):
    def test_sin_git_pendiente_y_metrica_0(self):  # (10)
        with mock.patch("shutil.which", return_value=None):
            res = anclaje.anclar(self.cfg, self.con)
        self.assertFalse(res["anclado"])
        self.assertIn("git no encontrado", res["aviso"])
        v = self.con.execute("SELECT valor FROM ops_metrics WHERE clave = "
                             "'registro.anclajes'").fetchone()[0]
        self.assertEqual(v, 0.0)

    def test_estado_sin_git(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(anclaje.estado_anclaje(self.reg), "sin git")


@unittest.skipUnless(HAY_GIT, "git no disponible en el sandbox")
class TestAnclajeConGit(Base):
    def test_anclar_crea_repo_y_commit(self):
        res = anclaje.anclar(self.cfg, self.con)
        self.assertTrue(res["anclado"])
        self.assertIsNotNone(res["commit"])
        self.assertTrue((self.reg / ".git").is_dir())
        self.assertEqual(anclaje.estado_anclaje(self.reg), "anclado")
        v = self.con.execute("SELECT valor FROM ops_metrics WHERE clave = "
                             "'registro.anclajes'").fetchone()[0]
        self.assertEqual(v, 1.0)

    def test_commit_vacio_sin_cambios(self):  # trampa 10
        anclaje.anclar(self.cfg, self.con)
        res = anclaje.anclar(self.cfg, self.con)   # nada nuevo → sin commit
        self.assertEqual(res["aviso"], "anclaje: sin cambios")

    def test_truncar_tras_anclaje_rompe_estado(self):  # §6: borrado del final
        anclaje.anclar(self.cfg, self.con)
        f = self.reg / anclaje.FICHERO
        f.write_bytes(f.read_bytes()[:-5])
        self.assertEqual(anclaje.estado_anclaje(self.reg), "pendiente")

    def test_rutas_con_espacios_y_acentos(self):  # trampa Hopper: argv lista
        self.assertIn(" ", str(self.reg))         # el tmp ya lleva espacio/acentos
        res = anclaje.anclar(self.cfg, self.con)
        self.assertTrue(res["anclado"])


class TestAnclajeSinSenales(Base):  # D-078 (segunda prueba Windows, H8)
    def test_registro_vacio_es_aviso_no_fallo(self):
        (self.reg / anclaje.FICHERO).unlink()      # aún no se ha sellado nada
        res = anclaje.anclar(self.cfg, self.con)
        self.assertFalse(res["anclado"])
        self.assertEqual(res["aviso"], "anclaje: sin señales selladas que anclar")
        self.assertEqual(res["n_lineas"], 0)
        v = self.con.execute("SELECT valor FROM ops_metrics WHERE clave = "
                             "'registro.anclajes'").fetchone()[0]
        self.assertEqual(v, 0.0)


class TestAnclajeError(Base):  # rev. Dijkstra M3
    def test_anclaje_error_es_sibila_error(self):
        # Cae en el handler accionable de la CLI, nunca en el genérico
        from sibila import SibilaError
        self.assertTrue(issubclass(anclaje.AnclajeError, SibilaError))

    def test_fallo_git_se_propaga_como_sibila_error(self):
        # git "presente" pero roto (returncode != 0) → AnclajeError(SibilaError)
        from sibila import SibilaError
        with mock.patch.object(anclaje, "_git", return_value="/usr/bin/git"), \
                mock.patch.object(anclaje, "_run") as r:
            r.return_value = SimpleNamespace(returncode=1,
                                             stderr="repo corrupto", stdout="")
            with self.assertRaises(SibilaError):
                anclaje.anclar(self.cfg, self.con)


if __name__ == "__main__":
    unittest.main()

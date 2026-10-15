"""Tests puros de procesado/bot_heur.py (umbrales FIJADOS, plan Lovelace §4.6).
Ninguna flag usa reloj: solo timestamps del contexto."""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"  # sandbox: pip --target persistente
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import unittest
from datetime import datetime, timedelta, timezone

from sibila.procesado.bot_heur import BOT_VERSION, ContextoBot, flags

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _ctx(**kw):
    base = dict(published_at=_iso(T0 + timedelta(days=1)),
                fetched_at=_iso(T0 + timedelta(days=1, seconds=5)),
                author_hash="ab" * 16,
                texto_limpio="texto normal variado con palabras distintas cada dia",
                historial_autor=())
    base.update(kw)
    return ContextoBot(**base)


class TestBot(unittest.TestCase):
    def test_version(self):
        self.assertEqual(BOT_VERSION, "bot-1")

    def test_cuatro_claves_siempre(self):
        f = flags(_ctx())
        self.assertEqual(set(f), {"regularidad", "plantilla", "marcador", "rafaga"})
        self.assertTrue(all(isinstance(v, bool) for v in f.values()))

    def test_regularidad_cv_cero(self):
        # Serie fija: intervalos de exactamente 1 h → CV = 0 < 0,1
        hist = tuple(_iso(T0 - timedelta(hours=6 - k)) for k in range(6))
        self.assertTrue(flags(_ctx(historial_autor=hist))["regularidad"])

    def test_regularidad_irregular(self):
        hist = tuple(_iso(T0 - timedelta(hours=int(h)))
                     for h in (200, 150, 149, 40, 2, 1))
        self.assertFalse(flags(_ctx(historial_autor=hist))["regularidad"])

    def test_regularidad_no_evaluable(self):
        # <5 publicaciones o author None → False (no evaluable ≠ sospechoso)
        hist = tuple(_iso(T0 - timedelta(hours=3 - k)) for k in range(4))
        self.assertFalse(flags(_ctx(historial_autor=hist))["regularidad"])
        hist6 = tuple(_iso(T0 - timedelta(hours=6 - k)) for k in range(6))
        self.assertFalse(flags(_ctx(author_hash=None, historial_autor=hist6))["regularidad"])

    def test_plantilla_repetido(self):
        # Doc 90 % repetido: 1 − |únicos|/|totales| ≥ 0,8
        texto = " ".join(["compra ya ahora"] * 20 + ["oferta unica limitada"])
        self.assertTrue(flags(_ctx(texto_limpio=texto))["plantilla"])

    def test_plantilla_variado(self):
        texto = " ".join(f"palabra{k} distinta{k} siempre{k}" for k in range(20))
        self.assertFalse(flags(_ctx(texto_limpio=texto))["plantilla"])

    def test_plantilla_pocos_trigramas(self):
        self.assertFalse(flags(_ctx(texto_limpio="uno dos tres"))["plantilla"])

    def test_marcador(self):
        t = "hola, as an ai language model no puedo opinar sobre eso"
        self.assertTrue(flags(_ctx(texto_limpio=t))["marcador"])
        self.assertTrue(flags(_ctx(texto_limpio="lo siento, no puedo ayudar"))["marcador"])
        self.assertFalse(flags(_ctx())["marcador"])

    def test_rafaga_21_en_una_hora(self):
        hist = tuple(_iso(T0 + timedelta(minutes=2 * k)) for k in range(20))
        ctx = _ctx(published_at=_iso(T0 + timedelta(minutes=40)),
                   historial_autor=hist)
        self.assertTrue(flags(ctx)["rafaga"])   # 21 publicaciones ≤ 3 600 s

    def test_rafaga_19_no(self):
        hist = tuple(_iso(T0 + timedelta(minutes=3 * k)) for k in range(18))
        ctx = _ctx(published_at=_iso(T0 + timedelta(minutes=54)),
                   historial_autor=hist)
        self.assertFalse(flags(ctx)["rafaga"])  # 18 + doc = 19 < 20 en ~1 h

    def test_rafaga_sin_autor(self):
        hist = tuple(_iso(T0 + timedelta(minutes=k)) for k in range(30))
        self.assertFalse(flags(_ctx(author_hash=None, historial_autor=hist))["rafaga"])


if __name__ == "__main__":
    unittest.main()

"""Arnés de escenario T1: corre los 32 días congelados con dobles inyectados.

Factoría de tests (tests/helpers/arnes.py): detector falso 'es', mini-léxicos
de fixtures (verificar_sha=False), enviar fake en memoria, fuente 't1'.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

_TESTS = Path(__file__).resolve().parent.parent
_NUCLEO = _TESTS.parent
for p in (str(_NUCLEO), str(_NUCLEO / "deps")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tests.helpers import sintetico_e2e as gen      # noqa: E402
from tests.test_procesa import DetectorFalso, _lex  # noqa: E402
from sibila import corre, db                         # noqa: E402

AHORA_1 = datetime(2026, 6, 2, 6, 0, 0, tzinfo=timezone.utc)  # observación día 1
FUENTE = "t1"


def preparar_bd(tmp: Path) -> SimpleNamespace:
    """BD vacía con la fuente 't1' dada de alta. Devuelve cfg."""
    cfg = SimpleNamespace(data_dir=Path(tmp) / "datos", db_path=Path(tmp) / "sibila.db",
                          secretos={"telegram_token": "t", "telegram_chat": "c"})
    db.init_db(cfg.db_path)
    con = db.connect(cfg.db_path)
    with db.tx(con):
        con.execute("INSERT INTO sources(nombre, tipo, idioma, peso)"
                    " VALUES (?, 'web', 'es', 1.0)", (FUENTE,))
    con.close()
    return cfg


def ahora_del_dia(i: int) -> datetime:
    """Observación de corrida del día i (0-based): D+1T06:00:00Z (D-047 §2)."""
    return AHORA_1 + timedelta(days=i)


def correr_escenario(cfg, tmp: Path, *, dias: int = gen.N_DIAS, envios=None,
                     resumenes=None):
    """Corre días 1..`dias` con fixtures. Devuelve lista de envíos (canal, msg,
    ahora) en orden. `resumenes` (lista opcional) recoge el resumen por día."""
    gen.escribir_escenario(Path(tmp) / "feeds")
    envios = envios if envios is not None else []
    det, lex = DetectorFalso("es"), _lex()
    for i in range(dias):
        d = date.fromordinal(gen.DIA_1.toordinal() + i)
        ahora = ahora_del_dia(i)
        r = corre.ejecutar_dia(cfg, dia=d.isoformat(), ahora=ahora,
                               fixtures={FUENTE: Path(tmp) / "feeds" / f"{d}.xml"},
                               detector=det, lexicos=lex,
                               enviar=lambda c, ch, m, a=ahora: envios.append((a, ch, m)))
        if resumenes is not None:
            resumenes.append(r)
    return envios

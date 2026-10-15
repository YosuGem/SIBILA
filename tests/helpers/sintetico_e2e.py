"""Generador RSS sintético de T1 (tests/helpers/sintetico_e2e.py).

ÚNICO generador del corpus congelado T1 (D-047): 32 días × (tema + emoción),
fechas absolutas 2026-06-01…2026-07-02, 576 documentos. DETERMINISTA: mismo
input → mismos bytes (T-T1-12: sha256 estable; nada de reloj ni aleatoriedad).

Cada item RSS: link/guid único https://t1.invalid/{dia}/{i}, pubDate RFC-2822
UTC, cuerpo corto con token único. Dos carriles:
- Tema: `n_tema` docs contienen `terremoto` + palabras únicas por doc (sin
  near-dup, sin acompañantes fijos que alerten).
- Emoción ES: 11 docs/día con el mismo cuerpo emocional del día + token
  tok0000..tok0010 → media diaria exacta y n_efectivo ∈ {10,9998; 10,9999}
  (≥ MIN_N_EFECTIVO_EMO=10.0; assert temprano en el test, no en el gate).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from email.utils import format_datetime
from pathlib import Path

# valencia congelada → palabra del mini-léxico ES (v' = 2v − 1 tras reescalado):
# espera 0,7→0,4 · sorpresa 0,75→0,5 · alegria 0,95→0,9 (plan §3.1)
PALABRA_POR_VALENCIA = {0.4: "espera", 0.5: "sorpresa", 0.9: "alegria"}

# Vector (j): docs/día con `terremoto` (días 1-28 baseline, 29-31 pico, 32=0)
CONTEOS_TEMA = ([5, 6, 5, 7, 5, 8, 4, 7, 8, 7, 9, 7, 10, 6] * 2
                + [12, 12, 12] + [0])
# Vector (k): valencia ES por día (días 1-28 alterna 0,4/0,5; 29-32 = 0,9)
VALENCIAS = ([0.4, 0.5] * 14 + [0.9, 0.9, 0.9, 0.9])

DIA_1 = date(2026, 6, 1)          # lunes
N_DIAS = 32                       # 2026-06-01 … 2026-07-02
DOCS_EMO_POR_DIA = 11
DOCS_TEMA_TOTAL = 224             # 188 baseline + 36 pico
DOCS_TOTAL = 576                  # 224 tema + 352 emoción


def _item(dia: date, i: int, cuerpo: str) -> str:
    pub = format_datetime(datetime(dia.year, dia.month, dia.day, 10, 0, 0,
                                   tzinfo=timezone.utc), usegmt=True)
    return (f"    <item>\n"
            f"      <title>doc {dia} {i}</title>\n"
            f"      <link>https://t1.invalid/{dia}/{i}</link>\n"
            f"      <guid>https://t1.invalid/{dia}/{i}</guid>\n"
            f"      <pubDate>{pub}</pubDate>\n"
            f"      <description>{cuerpo}</description>\n"
            f"    </item>\n")


def generar_dia(dia: date, n_tema: int, valencia: float) -> bytes:
    """RSS 2.0 UTF-8 del día: n_tema docs de tema + 11 de emoción."""
    palabra = PALABRA_POR_VALENCIA[valencia]   # KeyError temprano si no es ley
    items = []
    for i in range(n_tema):  # palabras únicas por doc: sin near-dup (R-T1-1)
        cuerpo = " ".join(["terremoto"]
                          + [f"w{dia.strftime('%m%d')}{i}{j}" for j in range(6)])
        items.append(_item(dia, i, cuerpo))
    for i in range(DOCS_EMO_POR_DIA):
        # token ÚNICO POR DÍA (tokMMDDNN): el plan decía tok0000..tok0010, pero
        # repetir el mismo cuerpo otro día lo mata por dup_cont en ingesta. El
        # token no casa con el léxico en ninguna de las dos formas y su df
        # intra-día sigue siendo 1 → V y n_efectivo congelados no se mueven.
        items.append(_item(dia, n_tema + i, f"{palabra} {palabra} {palabra} "
                                            f"tok{dia.strftime('%m%d')}{i:02d}"))
    rss = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
           "<rss version=\"2.0\">\n  <channel>\n"
           f"    <title>t1 {dia}</title>\n"
           + "".join(items) +
           "  </channel>\n</rss>\n")
    return rss.encode("utf-8")


def verdad(dia: date) -> "tuple[int, float]":
    """(n_tema, valencia) congelados del día; fuera del escenario → KeyError."""
    i = (dia - DIA_1).days
    return CONTEOS_TEMA[i], VALENCIAS[i]


def escribir_escenario(directorio: Path) -> dict:
    """Escribe {dia}.xml de los 32 días. Devuelve {date: Path}."""
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    rutas = {}
    for i in range(N_DIAS):
        dia = date.fromordinal(DIA_1.toordinal() + i)
        ruta = directorio / f"{dia.isoformat()}.xml"
        ruta.write_bytes(generar_dia(dia, *verdad(dia)))
        rutas[dia] = ruta
    return rutas

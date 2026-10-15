"""Referencia GDELT (`sibila informe --actualizar-gdelt`, Bloque 7).

Subacción ESCRITORA aparte (M3 de Turing, DECIDIDO): el UPSERT en gdelt_ref es
escritura y JAMÁS comparte ejecución con la lectura mode=ro del informe.
Reglas:
- Vacío = SIN FILA, nunca n=0 persistido (spec §5, TP-N12; la ausencia de fila
  ES el estado "pendiente" y permite el reintento del día siguiente).
- UNA tx por tema (aislamiento: un tema caído no arrastra a los demás).
- Red: requests con timeout 30 s; `descargar` inyectable en tests.
- GDELT es SOLO referencia (D-008): aquí solo se cuenta titulares.
"""
from __future__ import annotations

import logging
import sqlite3

from . import SibilaError, db

log = logging.getLogger("sibila.gdelt")

TIMEOUT_RED = 30
URL_GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"


class GdeltError(SibilaError):
    """Fallo previsto de la descarga/persistencia GDELT."""


def descargar_red(tema: str, day: str) -> list:
    """Titulares del día para el tema (GDELT DOC API). Vacío = n/d."""
    import requests
    r = requests.get(URL_GDELT, params={
        "query": tema, "mode": "artlist", "maxrecords": 250,
        "startdatetime": day.replace("-", "") + "000000",
        "enddatetime": day.replace("-", "") + "235959",
        "format": "json"}, timeout=TIMEOUT_RED)
    r.raise_for_status()
    return r.json().get("articles", [])


def actualizar(cfg, con, *, temas, dias, ahora=None, descargar=None) -> dict:
    """UPSERT gdelt_ref por (tema, día) con n = titulares; vacío → sin fila.
    Devuelve {escritos, vacios, fallos, avisos}."""
    descargar = descargar or descargar_red
    res = {"escritos": 0, "vacios": 0, "fallos": 0, "avisos": []}
    for tema in temas:
        for day in dias:
            try:
                articulos = descargar(tema, day)
            except Exception as e:   # red caída: el tema no arrastra a los demás
                res["fallos"] += 1
                res["avisos"].append(f"gdelt {tema} {day}: {e}")
                continue
            if not articulos:
                res["vacios"] += 1   # n/d: JAMÁS se persiste n=0 (TP-N12)
                continue
            try:
                with db.tx(con):
                    con.execute(
                        "INSERT INTO gdelt_ref(tema, day, n, fetched_at)"
                        " VALUES (?, ?, ?, ?)"
                        " ON CONFLICT(tema, day) DO UPDATE SET n = excluded.n,"
                        " fetched_at = excluded.fetched_at",
                        (tema, day, len(articulos), db.now_iso()))
                res["escritos"] += 1
            except sqlite3.Error as e:
                raise GdeltError(f"gdelt {tema} {day}: {e}") from e
    return res


def temas_de_la_semana(con, desde: str, hasta: str, limite: int = 5) -> list:
    """Temas candidatos a referencia GDELT: los de las señales recientes
    (confirmado+inmaduro), ordenados por score z_r máximo."""
    return [r[0] for r in con.execute(
        "SELECT t.text, MAX(s.score) FROM signals s JOIN terms t"
        " ON t.id = s.target_id WHERE s.day BETWEEN ? AND ? AND s.metric = 'z_r'"
        " AND s.status IN ('confirmado', 'inmaduro')"
        " GROUP BY t.text ORDER BY 2 DESC LIMIT ?", (desde, hasta, limite))]

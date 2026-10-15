#!/usr/bin/env python3
"""resumen.py — ritual de 30 segundos de Yosu (plan Bloque 3, C3).

Qué hace: abre la base EN MODO SOLO LECTURA y muestra lo recolectado en las últimas
24 h por fuente (nuevos · duplicados · errores), el total de documentos y la última
ingesta. Exit 1 + [AVISO] si no hubo ingesta en 24 h (bandera roja del día).

Por qué existe: sqlite3.exe no viene con Windows y `sibila check` queda CONGELADO
(150 tests dependen de su salida). Stdlib puro; NUNCA escribe en la base.

Uso:  .venv\\Scripts\\python.exe resumen.py        (en Hermes)
      python3 resumen.py                            (sandbox)
Ruta de la BD: variable SIBILA_DB_PATH si existe; si no, <repo>/datos/sibila.db.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIMEOUT_S = 30  # busy_timeout POR CONEXIÓN (rev. Liskov 1: no se hereda de db.py)


def _ruta_db() -> Path:
    if os.environ.get("SIBILA_DB_PATH"):
        return Path(os.environ["SIBILA_DB_PATH"]).resolve()
    return Path(__file__).resolve().parent / "datos" / "sibila.db"


def _ruta_fuentes() -> Path:
    """fuentes.toml de producción (rev. Hamilton N1: cruzar fuentes SIN actividad)."""
    return Path(__file__).resolve().parent / "fuentes.toml"


def _fuentes_habilitadas() -> list[str]:
    """Secciones de fuentes.toml no deshabilitadas. Si no se puede leer, devuelve
    [] y el cruce se omite (degradar con aviso, nunca romper el ritual)."""
    ruta = _ruta_fuentes()
    try:
        with ruta.open("rb") as f:
            datos = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"[AVISO] no se pudo leer {ruta.name} ({e}); no se cruza la lista de fuentes",
              file=sys.stderr)
        return []
    return [n for n, cfg in datos.items()
            if isinstance(cfg, dict) and cfg.get("habilitada", True)]


def main() -> int:
    ruta = _ruta_db()
    if not ruta.exists():
        print(f"[FALLO] no existe la base de datos ({ruta}); ejecuta la instalación "
              f"(instalar.bat) o revisa SIBILA_DB_PATH", file=sys.stderr)
        return 1
    try:
        # rev. Dijkstra B2: as_uri() escapa #, ?, %, espacios y usa slashes (una ruta
        # con '#' sin escapar haría abrir OTRA base distinta, silenciosamente)
        con = sqlite3.connect(ruta.as_uri() + "?mode=ro", uri=True, timeout=TIMEOUT_S)
    except sqlite3.Error as e:
        print(f"[FALLO] no se pudo abrir la base en solo-lectura: {e}", file=sys.stderr)
        return 1
    try:
        ahora = datetime.now(timezone.utc)
        desde = (ahora - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"=== resumen sibila · {ahora.strftime('%Y-%m-%dT%H:%M:%SZ')} (UTC) "
              f"· últimas 24 h ===")
        # claves: ingesta.{nuevos|duplicados_url|duplicados_contenido|errores}.{fuente}
        filas = con.execute(
            "SELECT clave, SUM(valor), MAX(ts) FROM ops_metrics"
            " WHERE clave LIKE 'ingesta.%' AND ts >= ? GROUP BY clave",
            (desde,)).fetchall()
        por_fuente: dict[str, dict[str, float]] = {}
        for clave, total, ts in filas:
            partes = clave.split(".")
            if len(partes) != 3:
                continue
            _prefijo, metrica, fuente = partes
            por_fuente.setdefault(fuente, {})[metrica] = total or 0.0
        if not por_fuente:
            print("  (sin actividad de ingesta en las últimas 24 h)")
        for fuente in sorted(por_fuente):
            m = por_fuente[fuente]
            dups = m.get("duplicados_url", 0.0) + m.get("duplicados_contenido", 0.0)
            print(f"  {fuente}: {int(m.get('nuevos', 0))} nuevos · {int(dups)} duplicados"
                  f" · {int(m.get('errores', 0))} errores")
        total_docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        ultima = con.execute(
            "SELECT MAX(ts) FROM ops_metrics WHERE clave LIKE 'ingesta.%'").fetchone()[0]
        print(f"documents total: {total_docs} · última ingesta: {ultima or '(nunca)'}")
        salida = 0
        # rev. Hamilton N1: una fuente que falla no escribe métricas y DESAPARECERÍA
        # del resumen (verde falso). Se cruza con fuentes.toml y se denuncia.
        for fuente in _fuentes_habilitadas():
            if fuente not in por_fuente:
                print(f"[AVISO] {fuente}: sin actividad en las últimas 24 h "
                      f"(¿fuente caída o tarea a medias? mira logs\\ingesta_tarea.log "
                      f"y logs\\sibila.log)")
                salida = 1
        if ultima is None or ultima < desde:  # ISO Z compara como texto
            print("[AVISO] no hubo ingesta en las últimas 24 h: revisa la tarea "
                  "programada y logs\\ingesta_tarea.log")
            salida = 1
        return salida
    except sqlite3.Error as e:
        print(f"[FALLO] error leyendo la base: {e}", file=sys.stderr)
        return 1
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())

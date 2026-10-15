#!/usr/bin/env python3
"""Sustituye los placeholders de una plantilla de tarea XML (tarea_ingesta.xml
/ tarea_diaria.xml) y escribe el XML final en UTF-16 LE con BOM — el formato
que acepta schtasks en Windows 11 real (D-077: la primera prueba real W11
demostró que UTF-8 sin BOM era RECHAZADO; la nota anterior que afirmaba lo
contrario era una hipótesis sin probar). La plantilla permanece en UTF-8;
la declaración del XML final se ajusta a UTF-16.

Guardas (rev. Dijkstra M4, heredadas): una ruta con & < > rompería el XML →
error claro. La sustitución es textual e idempotente en origen (la plantilla
nunca se toca; el final se regenera SIEMPRE).

Uso: python tools/preparar_tarea.py plantilla.xml destino.xml [RAIZ] [INICIO]
  INICIO: ISO local 'YYYY-MM-DDTHH:MM:SS'; defecto: mañana a las 07:00.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path


def preparar(plantilla: Path, destino: Path, raiz: str,
             inicio: "str | None" = None) -> Path:
    """Devuelve `destino` escrito. ValueError si la ruta rompería el XML."""
    if any(c in raiz for c in "&<>"):
        raise ValueError(f"la ruta contiene &, < o >: {raiz!r} "
                         "(instala en una ruta simple, p. ej. C:\\sibila)")
    if inicio is None:
        inicio = (datetime.now() + timedelta(days=1)).strftime(
            "%Y-%m-%dT07:00:00")
    xml = plantilla.read_text(encoding="utf-8")
    xml = xml.replace("{SIBILA_RAIZ}", raiz).replace("{START_BOUNDARY}", inicio)
    if "{" in xml and "}" in xml and ("{SIBILA_" in xml or "{START_" in xml):
        raise ValueError("quedan placeholders sin sustituir")
    # UTF-16 LE con BOM (FF FE): lo que schtasks acepta de verdad (D-077).
    xml = xml.replace('encoding="UTF-8"', 'encoding="UTF-16"', 1)
    destino.write_bytes(b"\xff\xfe" + xml.encode("utf-16-le"))
    return destino


def main(argv) -> int:
    if len(argv) < 3:
        print("uso: preparar_tarea.py PLANTILLA DESTINO [RAIZ] [INICIO_ISO]")
        return 2
    raiz = argv[3] if len(argv) > 3 else str(Path.cwd())
    inicio = argv[4] if len(argv) > 4 else None
    try:
        destino = preparar(Path(argv[1]), Path(argv[2]), raiz, inicio)
    except (ValueError, OSError) as e:
        print(f"[FALLO] {e}")
        return 1
    print(f"[OK] tarea preparada: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

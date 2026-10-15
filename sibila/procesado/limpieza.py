"""Limpieza de texto (spec §6.1). Función pura, O(n), sin backtracking anidado
(todos los cuantificadores acotados: anti-ReDoS por construcción).

Entrada máxima documentada: 1 MB (la capa de datos recorta antes, trampa T-12).
Nunca lanza por contenido; ValueError solo si body no es str.
"""
import html
import re
import unicodedata

_RE_TAG = re.compile(r"<[^>]{1,1024}>")
_RE_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S{1,2048}")
_RE_EMAIL = re.compile(r"\S{1,320}@\S{1,320}")
_RE_WS = re.compile(r"\s+")
_RE_CITA = re.compile(r"(?m)^> .*$")


def limpiar(body: str) -> str:
    """NFKC → sin URLs/HTML/citas "> " → minúsculas. Devuelve '' si no queda
    nada. Nunca lanza por contenido. Idempotente (test guardián)."""
    if not isinstance(body, str):
        raise ValueError("limpiar espera str")
    t = unicodedata.normalize("NFKC", body)
    t = html.unescape(t)
    t = _RE_TAG.sub("", t)
    t = _RE_URL.sub("", t)
    t = _RE_EMAIL.sub("", t)
    # Citas "> ..." (correo/markdown) se eliminan enteras; el greentext de
    # 4chan (">implicando", SIN espacio tras '>') se CONSERVA (rev. H5).
    t = _RE_CITA.sub("", t)
    t = t.casefold()
    return _RE_WS.sub(" ", t).strip()

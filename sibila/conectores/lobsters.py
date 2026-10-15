"""Conector Lobsters (RSS) + parser de feeds COMPARTIDO con Mastodon y el fallback de Reddit.
feedparser hace el trabajo sucio: fechas con offset → struct_time en UTC."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from .base import (Conector, HttpError, RawDoc, UA, clave_doc, descargar, dump_cursor)

log = logging.getLogger("sibila.conectores.lobsters")


def _fecha_de(e) -> datetime | None:
    """published_parsed/updated_parsed son struct_time EN UTC (feedparser ya aplicó el offset)."""
    for campo in ("published_parsed", "updated_parsed"):
        t = e.get(campo)
        if t:
            dt = datetime(*t[:6], tzinfo=timezone.utc)
            return dt if dt.year >= 2000 else None
    return None


def _cuerpo_de(e) -> str:
    if e.get("content"):  # Atom: lista de dicts {type, value}
        try:
            valor = e.content[0].get("value", "")
            if valor:
                return valor
        except (AttributeError, IndexError):
            pass
    return e.get("description") or e.get("title") or ""


def _autor_de(e) -> str | None:
    """Quirks verificados: RSS de lobste.rs prefija 'by '; el Atom de Reddit usa '/u/x'.
    El prefijo se quita AQUÍ (parse), no en ingesta (plan Hopper §6-§7; rev. Dijkstra M5)."""
    autor = e.get("author")
    if not isinstance(autor, str):
        return None
    autor = autor.strip()
    if autor.startswith("by "):
        autor = autor[3:]
    elif autor.startswith("/u/"):
        autor = autor[3:]
    return autor.strip() or None


def parsear_feed(contenido: bytes, *, fuente: str) -> tuple[list[RawDoc], dict]:
    """RSS o Atom → RawDocs. Saltadas: sin link/guid http Y sin cuerpo (malformada), o
    entrada con TIPOS rotos (rev. Dijkstra B4: una entrada venenosa NUNCA rompe el lote).
    XML irrecuperable (bozo sin entradas) → HttpError('parse'), nunca lote vacío silencioso.
    XML truncado CON entradas (bozo=1) → se procesan las válidas con aviso (plan T-C4)."""
    import feedparser
    feed = feedparser.parse(contenido)
    if feed.bozo and not feed.entries:
        raise HttpError("parse", f"{fuente}: XML/feed malformado ({feed.bozo_exception})")
    if feed.bozo:
        log.warning("%s: XML/feed truncado (bozo); se procesan las %d entradas válidas",
                    fuente, len(feed.entries))
    docs, saltadas = [], 0
    for e in feed.entries:
        try:
            link = e.get("link") or e.get("guid") or e.get("id")
            if link is not None and not isinstance(link, str):
                link = None
            if link and not link.lower().startswith(("http://", "https://")):
                link = None  # URN de Mastodon y similares: NUNCA llega como url (T-C3)
            cuerpo = _cuerpo_de(e)
            if not isinstance(cuerpo, str):
                cuerpo = ""
            if link is None and not cuerpo:
                saltadas += 1
                continue
            docs.append(RawDoc(
                fuente=fuente,
                url=link,
                author_raw=_autor_de(e),
                published_at=_fecha_de(e),
                body=cuerpo,
                crudo=json.dumps(dict(e), ensure_ascii=False, sort_keys=True,
                                 default=str),
                lang=None,
            ))
        except Exception:  # entrada venenosa de cualquier tipo: contada, lote intacto
            saltadas += 1
            log.info("%s: entrada malformada saltada", fuente)
    return docs, {"saltadas": saltadas}


class Lobsters(Conector):
    nombre = "lobsters"

    def fetch(self, cfg, cursor, *, sesion=None, dormir=None):
        dormir = dormir or time.sleep
        datos, vistos = self._fuente_y_vistos(cursor)
        if cfg.get("fixture"):
            with open(cfg["fixture"], "rb") as f:
                contenido = f.read()
            cabeceras = {}
        else:
            sesion = sesion or _sesion_real()
            contenido, cabeceras = descargar(
                sesion, cfg["url"],
                cabeceras=self._cabeceras_condicionales(datos), dormir=dormir)
            if contenido is None:  # 304: sin novedades, todo sigue igual
                return [], cursor
        docs, _cont = parsear_feed(contenido, fuente="lobsters")
        emitidos, dups = self._dedup(docs, clave_doc, vistos)
        vistos.recortar()
        nuevo = vistos.como_dict()
        self._guardar_validadores(nuevo, cabeceras)
        return emitidos, dump_cursor(nuevo)


def _sesion_real():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s

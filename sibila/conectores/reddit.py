"""Conector Reddit: JSON .json con fallback RSS. El parsing es puro y separado de la E/S.

Fallback (plan Hopper §7, rev. Dijkstra M4): UN intento a .rss SOLO cuando el .json da
HTTP 403/404 o la RAÍZ del JSON es inválida (no JSON, o forma distinta de listing). Los
errores de red (5xx agotados, timeouts) NO disparan fallback: son fallo, no cambio de formato.
Doble fallo → HttpError."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from .base import (Conector, HttpError, RawDoc, UA, clave_doc, descargar, dump_cursor)

log = logging.getLogger("sibila.conectores.reddit")


def _epoch_a_utc(v) -> datetime | None:
    try:
        dt = datetime.fromtimestamp(float(v), tz=timezone.utc)
        return dt if dt.year >= 2000 else None
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def parsear(texto: str) -> tuple[list[RawDoc], dict]:
    """Listing JSON → RawDocs. Saltadas: kind!=t3, data no-dict, sin url/permalink Y sin
    texto, o entrada con TIPOS rotos (rev. Dijkstra B4: data lista, url entera… —formas
    reales de la API— se cuentan y el lote sigue). Raíz con forma no-listing → ValueError
    (fetch la trata como raíz inválida → fallback RSS)."""
    datos = json.loads(texto)  # JSONDecodeError la traduce fetch a fallback/HttpError
    if not isinstance(datos, dict):
        raise ValueError("raíz JSON no es un objeto (¿listing?)")
    data = datos.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("children"), list):
        raise ValueError("raíz JSON sin data.children (¿listing?)")
    docs, saltadas = [], 0
    for child in data["children"]:
        try:
            if not isinstance(child, dict) or child.get("kind") != "t3":
                saltadas += 1
                continue
            d = child.get("data")
            if not isinstance(d, dict):
                saltadas += 1
                continue
            url = d.get("url")
            if not isinstance(url, str) or not url.lower().startswith(
                    ("http://", "https://")):
                permalink = d.get("permalink")
                url = ("https://www.reddit.com" + permalink
                       if isinstance(permalink, str) and permalink.startswith("/")
                       else None)
            title = d.get("title") if isinstance(d.get("title"), str) else ""
            selftext = d.get("selftext") if isinstance(d.get("selftext"), str) else ""
            body = (title + "\n" + selftext).rstrip()
            if url is None and not body:
                saltadas += 1
                continue
            author = d.get("author")
            docs.append(RawDoc(
                fuente="reddit",
                url=url,
                author_raw=author if isinstance(author, str) else None,
                published_at=_epoch_a_utc(d.get("created_utc")),
                body=body,
                crudo=json.dumps(d, ensure_ascii=False, sort_keys=True, default=str),
                lang=None,
            ))
        except Exception:  # child venenoso de cualquier tipo: contado, lote intacto
            saltadas += 1
            log.info("reddit: child malformado saltado")
    return docs, {"saltadas": saltadas}


class Reddit(Conector):
    nombre = "reddit"

    def fetch(self, cfg, cursor, *, sesion=None, dormir=None):
        dormir = dormir or time.sleep
        datos, vistos = self._fuente_y_vistos(cursor)
        if cfg.get("fixture"):
            with open(cfg["fixture"], "rb") as f:
                contenido = f.read()
            cabeceras = {}
            docs, _cont = self._parsear_con_fallback(contenido, cfg, sesion, datos,
                                                     dormir, en_fixture=True)
        else:
            sesion = sesion or _sesion_real()
            url_json = cfg["url"]
            url_rss = url_json.replace(".json", ".rss")
            cab = self._cabeceras_condicionales(datos)
            try:
                contenido, cabeceras = descargar(sesion, url_json, cabeceras=cab,
                                                 dormir=dormir)
            except HttpError as e:
                if e.codigo in ("http_403", "http_404"):  # defensa Fase 0: fallback RSS
                    log.info("reddit: .json dio %s; un intento a %s", e.codigo, url_rss)
                    contenido, cabeceras = descargar(sesion, url_rss, cabeceras=cab,
                                                     dormir=dormir)
                    if contenido is None:
                        return [], cursor
                    docs, _cont = self._parsea_rss(contenido)
                else:  # 5xx agotado, red…: NO es un cambio de formato → fallo visible
                    raise
            else:
                if contenido is None:  # 304: sin novedades
                    return [], cursor
                docs, _cont = self._parsear_con_fallback(
                    contenido, cfg, sesion, datos, dormir)
        emitidos, dups = self._dedup(docs, clave_doc, vistos)
        vistos.recortar()
        nuevo = vistos.como_dict()
        self._guardar_validadores(nuevo, cabeceras)
        return emitidos, dump_cursor(nuevo)

    def _parsear_con_fallback(self, contenido, cfg, sesion, datos, dormir, *,
                              en_fixture=False):
        """JSON primero; raíz inválida → UN intento RSS (doble fallo → HttpError)."""
        try:
            return parsear(contenido.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, ValueError) as e:
            if en_fixture:
                raise HttpError("parse", f"reddit: JSON inválido ({e})") from e
            url_rss = cfg["url"].replace(".json", ".rss")
            log.info("reddit: raíz JSON inválida (%s); un intento a %s", e, url_rss)
            contenido_rss, _cab2 = descargar(
                sesion, url_rss,
                cabeceras=self._cabeceras_condicionales(datos), dormir=dormir)
            if contenido_rss is None:
                return [], {"saltadas": 0}
            return self._parsea_rss(contenido_rss)

    @staticmethod
    def _parsea_rss(contenido):
        from .lobsters import parsear_feed  # fallback RSS: mismo parser de feeds
        return parsear_feed(contenido, fuente="reddit")


def _sesion_real():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s

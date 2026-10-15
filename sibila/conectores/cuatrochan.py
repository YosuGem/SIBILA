"""Conector 4chan (catalog.json): parsing puro. Los hilos sin texto (solo imagen) se saltan:
no aportan nada a la lingüística."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from .base import (Conector, HttpError, RawDoc, UA, clave_doc, descargar, dump_cursor)

log = logging.getLogger("sibila.conectores.4chan")


def _epoch_a_utc(v) -> datetime | None:
    try:
        dt = datetime.fromtimestamp(int(v), tz=timezone.utc)
        return dt if dt.year >= 2000 else None
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def parsear(texto: str, *, tablon: str = "pol", paginas: int | None = None) -> tuple[list[RawDoc], dict]:
    """Catalog JSON (lista de páginas) → RawDocs. Saltadas: sin 'no'; sin sub NI com
    (hilo-imagen); o entrada con TIPOS rotos (rev. Dijkstra B4: root dict, sub entero,
    página no-dict… — contadas, el lote sigue). Raíz no-lista → ValueError (fetch la
    traduce a HttpError('parse'))."""
    datos = json.loads(texto)
    if not isinstance(datos, list):
        raise ValueError("raíz JSON no es una lista de páginas (¿catalog?)")
    docs, saltadas = [], 0
    for pagina in (datos[:paginas] if paginas else datos):
        if not isinstance(pagina, dict) or not isinstance(pagina.get("threads"), list):
            saltadas += 1
            continue
        for hilo in pagina["threads"]:
            try:
                if not isinstance(hilo, dict):
                    saltadas += 1
                    continue
                no = hilo.get("no")
                if not isinstance(no, int):
                    saltadas += 1
                    continue
                sub = hilo.get("sub") if isinstance(hilo.get("sub"), str) else ""
                com = hilo.get("com") if isinstance(hilo.get("com"), str) else ""
                body = (sub + "\n" + com).rstrip()
                if not body:
                    saltadas += 1
                    continue
                docs.append(RawDoc(
                    fuente="4chan",
                    url=f"https://boards.4chan.org/{tablon}/thread/{no}",
                    author_raw=None,  # 4chan es anónimo por diseño
                    published_at=_epoch_a_utc(hilo.get("time")),
                    body=body,
                    crudo=json.dumps(hilo, ensure_ascii=False, sort_keys=True,
                                     default=str),
                    lang=None,
                ))
            except Exception:  # hilo venenoso de cualquier tipo: contado, lote intacto
                saltadas += 1
                log.info("4chan: hilo malformado saltado")
    return docs, {"saltadas": saltadas}


class CuatroChan(Conector):
    nombre = "4chan"

    def fetch(self, cfg, cursor, *, sesion=None, dormir=None):
        dormir = dormir or time.sleep
        datos, vistos = self._fuente_y_vistos(cursor)
        tablon = cfg.get("tablon", "pol")
        paginas = cfg.get("paginas")
        if cfg.get("fixture"):
            with open(cfg["fixture"], "rb") as f:
                contenido = f.read()
            cabeceras = {}
        else:
            import requests
            sesion = sesion or requests.Session()
            contenido, cabeceras = descargar(
                sesion, f"https://a.4cdn.org/{tablon}/catalog.json",
                cabeceras=self._cabeceras_condicionales(datos), dormir=dormir)
            if contenido is None:  # 304: sin novedades (rev. Hamilton M8: rama alcanzable)
                return [], cursor
        try:
            docs, _cont = parsear(contenido.decode("utf-8", errors="replace"),
                                  tablon=tablon, paginas=paginas)
        except (json.JSONDecodeError, ValueError) as e:
            raise HttpError("parse", f"4chan: JSON inválido ({e})") from e
        emitidos, dups = self._dedup(docs, clave_doc, vistos)
        vistos.recortar()
        nuevo = vistos.como_dict()
        self._guardar_validadores(nuevo, cabeceras)
        return emitidos, dump_cursor(nuevo)

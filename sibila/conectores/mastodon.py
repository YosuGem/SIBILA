"""Conector Mastodon (Atom de etiqueta): reutiliza parsear_feed; url derivada de instancia/tag."""
from __future__ import annotations

import time

from .base import Conector, clave_doc, descargar, dump_cursor
from .lobsters import parsear_feed


class Mastodon(Conector):
    nombre = "mastodon"

    @staticmethod
    def url_de(cfg) -> str:
        if cfg.get("url"):
            return cfg["url"]
        return f"https://{cfg.get('instancia', 'mastodon.social')}/tags/{cfg.get('tag', 'ai')}.atom"

    def fetch(self, cfg, cursor, *, sesion=None, dormir=None):
        dormir = dormir or time.sleep
        datos, vistos = self._fuente_y_vistos(cursor)
        if cfg.get("fixture"):
            with open(cfg["fixture"], "rb") as f:
                contenido = f.read()
            cabeceras = {}
        else:
            import requests
            sesion = sesion or requests.Session()
            contenido, cabeceras = descargar(
                sesion, self.url_de(cfg),
                cabeceras=self._cabeceras_condicionales(datos), dormir=dormir)
            if contenido is None:  # 304: sin novedades
                return [], cursor
        docs, _cont = parsear_feed(contenido, fuente="mastodon")
        emitidos, dups = self._dedup(docs, clave_doc, vistos)
        vistos.recortar()
        nuevo = vistos.como_dict()
        self._guardar_validadores(nuevo, cabeceras)
        return emitidos, dump_cursor(nuevo)

"""Conectores de ingesta (spec §4.1/§6). Cada conector es 90 % parsing PURO (sin E/S):
fetch solo descarga/lee y delega en parsear(); los tests T1 viven de fixtures.
La validación del contrato y los hashes de persistencia viven en sibila.ingesta (D-B2-07)."""
from .base import (Conector, CursorVistos, HttpError, RawDoc, UA, cargar_fuentes,
                   clave_doc, descargar, dump_cursor, parse_cursor)
from .cuatrochan import CuatroChan
from .lobsters import Lobsters
from .mastodon import Mastodon
from .reddit import Reddit

REGISTRO = {
    "reddit": Reddit,
    "lobsters": Lobsters,
    "mastodon": Mastodon,
    "4chan": CuatroChan,
}


def conectores_habilitados(fuentes: dict) -> list:
    """Instancia los conectores habilitados del fuentes.toml ya cargado.
    Nombre desconocido → ValueError amable (exit 2 en CLI)."""
    habilitados = []
    for nombre, cfg in fuentes.items():
        if nombre not in REGISTRO:
            raise ValueError(
                f"fuente desconocida '{nombre}'; conocidas: {sorted(REGISTRO)}")
        if cfg.get("habilitada", True):
            habilitados.append(REGISTRO[nombre](cfg))
    return habilitados


__all__ = ["Conector", "CuatroChan", "CursorVistos", "HttpError", "Lobsters",
           "Mastodon", "RawDoc", "Reddit", "REGISTRO", "UA", "cargar_fuentes",
           "clave_doc", "conectores_habilitados", "descargar", "dump_cursor",
           "parse_cursor"]

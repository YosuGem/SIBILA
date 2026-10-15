"""Base de los conectores: contrato RawDoc, utilidades puras y E/S tonta.

Reglas de oro (planes Hopper/Liskov bloque 2):
- parsear() es PURO (bytes/str → RawDocs); jamás toca red ni disco → testeable sin fixtures de red.
- La E/S vive en descargar() y es pequeña y tonta.
- El cursor es UN STRING opaco para la persistencia; el conector lo serializa (JSON interno).
- El conector entrega URL y body CRUDOS: NO normaliza URLs, NO hashea para persistencia
  (eso es de ingesta.py, D-B2-07); aquí solo vive la clave de dedup del cursor.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger("sibila.conectores")

UA = "sibila-nucleo (programa de investigacion local; contacto: operador)"


@dataclass(frozen=True)
class RawDoc:
    """Documento crudo (contrato §4.1). Invariantes que ingesta.py HACE CUMPLIR:
    published_at: tz-aware UTC ESTRICTO o None (jamás naive ni otra zona).
    body: str; puede ser "" SOLO si hay url. url: http(s) o None.
    crudo: str no vacío (respaldo de hash cuando url es None)."""
    fuente: str
    url: str | None
    author_raw: str | None
    published_at: datetime | None
    body: str
    crudo: str
    lang: str | None = None


def clave_doc(doc: RawDoc) -> str:
    """Clave de dedup del cursor: la url si la hay; si no, 'h:' + sha256(crudo)[:32]
    (rev. Dijkstra B3/Hamilton B2: un PREFIJO del crudo colisiona entre docs distintos
    del mismo autor sin link → falso duplicado PERMANENTE vía cursor)."""
    if doc.url:
        return doc.url
    return "h:" + hashlib.sha256(doc.crudo.encode("utf-8")).hexdigest()[:32]


def parse_cursor(cursor: str | None) -> dict:
    """El cursor almacenado (string) → dict interno. Corrupción → dict vacío + aviso
    (NUNCA excepción: un cursor roto no puede tumbar la ingesta)."""
    if not cursor:
        return {}
    try:
        datos = json.loads(cursor)
        return datos if isinstance(datos, dict) else {}
    except (json.JSONDecodeError, TypeError):
        log.warning("cursor corrupto para una fuente; se reinicia vacío (no se pierden docs: dedup DB)")
        return {}


def dump_cursor(datos: dict) -> str:
    return json.dumps(datos, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class CursorVistos:
    """Conjunto acotado de vistos para dedup intra-lote y continuidad entre pasadas.
    Tope 1000 FIFO (plan Hopper §4: /pol/ mueve ~200 hilos/pasada)."""

    def __init__(self, maximo: int = 1000):
        self.maximo = maximo
        self._vistos: list[str] = []
        self._conjunto: set[str] = set()

    def visto(self, k: str) -> bool:
        return k in self._conjunto

    def agregar(self, k: str) -> None:
        if k in self._conjunto:
            return
        self._conjunto.add(k)
        self._vistos.append(k)

    def recortar(self) -> None:
        if len(self._vistos) > self.maximo:
            exceso = len(self._vistos) - self.maximo
            for k in self._vistos[:exceso]:
                self._conjunto.discard(k)
            self._vistos = self._vistos[exceso:]

    def como_dict(self) -> dict:
        return {"vistos": list(self._vistos)}

    @classmethod
    def desde_dict(cls, datos: dict, maximo: int = 1000) -> "CursorVistos":
        """Tolera cursores con TIPOS rotos (rev. Dijkstra M10: {'vistos': 123} o
        elementos no-texto tumbaron la fuente): cualquier desviación → vacío + aviso."""
        cv = cls(maximo)
        crudo = datos.get("vistos", [])
        if not isinstance(crudo, list) or not all(isinstance(k, str) for k in crudo):
            if crudo:  # había algo y estaba roto: consta
                log.warning("cursor con 'vistos' de tipo inesperado; se reinicia vacío")
            return cv
        for k in crudo:
            cv.agregar(k)
        return cv


class HttpError(Exception):
    """Error de descarga con código: 'red' (sin respuesta), 'http_403', 'parse', etc.
    Mensaje SIEMPRE en español accionable."""

    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo


def descargar(sesion, url: str, *, cabeceras: dict | None = None,
              reintentos: int = 3, espera: float = 2.0, dormir=time.sleep) -> tuple:
    """GET con reintentos (perfil del plan Hopper §5, rev. Dijkstra E4):
    - timeout=(5, 20) tupla SIEMPRE (conexión, lectura); backoff espera·2^i (2/4/8 s).
    - Reintenta SOLO ante 429 (honrando Retry-After entero), 5xx, Timeout y ConnectionError.
    - 4xx ≠ 429 → HttpError inmediata; agotados los intentos → HttpError('red', ...).
    - 304 → (None, cabeceras): sin novedades; el fetch decide (devuelve [], cursor).
    - Cabeceras de respuesta en MINÚSCULAS (HTTP/2 las manda así; rev. Dijkstra M8).
    `sesion` es inyectable (tests con stub); debe tener .get(url, headers=, timeout=).
    NUNCA lanza excepciones crudas: todo es HttpError con mensaje en español."""
    from requests.exceptions import ConnectionError as ReqConnError
    from requests.exceptions import RequestException, Timeout

    intentos = reintentos + 1
    ultimo: Exception | None = None
    for i in range(intentos):
        try:
            r = sesion.get(url, headers=cabeceras, timeout=(5, 20))
            hresp = {str(k).lower(): v for k, v in dict(r.headers).items()}
            if r.status_code == 200:
                return r.content, hresp
            if r.status_code == 304:
                return None, hresp
            if r.status_code == 429 and i < intentos - 1:
                espera_429 = espera * (2 ** i)
                try:
                    espera_429 = max(espera_429, int(hresp.get("retry-after", "0")))
                except ValueError:
                    pass
                dormir(espera_429)
                continue
            if r.status_code >= 500 and i < intentos - 1:
                dormir(espera * (2 ** i))
                continue
            raise HttpError(f"http_{r.status_code}",
                            f"{url}: HTTP {r.status_code}")
        except HttpError:
            raise  # la nuestra propia (4xx): no envolverla dos veces
        except (Timeout, ReqConnError) as e:
            ultimo = e
            if i < intentos - 1:
                dormir(espera * (2 ** i))
        except RequestException as e:  # otra excepción de requests: sin reintento
            raise HttpError("red", f"{url}: error de red ({e})") from e
        except Exception as e:  # rev. Dijkstra N2 r2: el docstring promete cero crudas
            raise HttpError("inesperado",
                            f"{url}: error inesperado de la sesión ({e})") from e
    raise HttpError("red", f"{url}: sin respuesta tras {intentos} intentos ({ultimo})")


_CLAVES_FUENTES = {"habilitada", "url", "fixture", "subreddit", "instancia", "tag",
                   "tablon", "paginas"}


def cargar_fuentes(ruta) -> dict:
    """Lee fuentes.toml → {nombre: cfg}. 'fixture' (relativa al propio toml) tiene
    precedencia sobre 'url': modo T1 sin red. Whitelist de claves (typo = error)."""
    ruta = Path(ruta)
    with ruta.open("rb") as f:
        datos = tomllib.load(f)
    fuentes = {}
    for nombre, cfg in datos.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"fuente '{nombre}': la sección debe ser una tabla")
        desconocidas = set(cfg) - _CLAVES_FUENTES
        if desconocidas:
            raise ValueError(
                f"fuente '{nombre}': claves desconocidas {sorted(desconocidas)}; "
                f"permitidas: {sorted(_CLAVES_FUENTES)}")
        if "habilitada" in cfg and not isinstance(cfg["habilitada"], bool):
            raise ValueError(f"fuente '{nombre}': 'habilitada' debe ser true/false")
        if "paginas" in cfg and not isinstance(cfg["paginas"], int):
            raise ValueError(f"fuente '{nombre}': 'paginas' debe ser entero")
        cfg = dict(cfg)
        if "fixture" in cfg and not Path(cfg["fixture"]).is_absolute():
            cfg["fixture"] = str((ruta.parent / cfg["fixture"]).resolve())
        fuentes[nombre] = cfg
    return fuentes


class Conector:
    """Base de conectores. fetch(cfg, cursor, ...) → (lista[RawDoc], cursor_nuevo_str).
    Parse devuelve (docs, contadores {'saltadas': n}); dedup intra-lote vive en fetch."""

    nombre = "?"

    def __init__(self, cfg: dict | None = None):
        self.cfg = dict(cfg or {})

    def fetch(self, cfg: dict, cursor: str | None, *, sesion=None,
              dormir=time.sleep) -> tuple[list, str]:
        raise NotImplantedError

    def _fuente_y_vistos(self, cursor: str | None):
        datos = parse_cursor(cursor)
        vistos = CursorVistos.desde_dict(datos)
        return datos, vistos

    @staticmethod
    def _cabeceras_condicionales(datos: dict) -> dict:
        """If-None-Match / If-Modified-Since desde el cursor (los 4 conectores, M8)."""
        cab = {"User-Agent": UA}
        if datos.get("etag"):
            cab["If-None-Match"] = datos["etag"]
        if datos.get("modified"):
            cab["If-Modified-Since"] = datos["modified"]
        return cab

    @staticmethod
    def _guardar_validadores(nuevo: dict, cabeceras: dict) -> None:
        """ETag/Last-Modified de la respuesta (claves ya en minúsculas) → cursor."""
        if cabeceras.get("etag"):
            nuevo["etag"] = cabeceras["etag"]
        if cabeceras.get("last-modified"):
            nuevo["modified"] = cabeceras["last-modified"]

    @staticmethod
    def _dedup(docs: list, clave, vistos: CursorVistos) -> tuple[list, int]:
        """Intra-lote keep-first + marca vistos entre pasadas (T-C4)."""
        emitidos, dups = [], 0
        for d in docs:
            k = clave(d)
            if vistos.visto(k):
                dups += 1
                continue
            vistos.agregar(k)
            emitidos.append(d)
        return emitidos, dups

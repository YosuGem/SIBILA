"""Carga y validación de configuración (spec §2/§3).

Precedencia: defaults del código < config.toml < config.local.toml < env SIBILA_*.
Secretos SOLO en config.local.toml o entorno; nunca en repr ni logs (trampa T4).
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from . import SibilaError

ENV_PREFIX = "SIBILA_"
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
DEFAULTS = {"general": {"data_dir": "datos", "log_level": "INFO"}}
KNOWN = {
    "general": {"data_dir", "db_path", "log_level"},
    "secretos": {"hmac_key", "telegram_token", "smtp_password",
                 "telegram_chat", "smtp_host", "smtp_usuario",
                 "smtp_puerto", "smtp_destino"},
}
ENV_MAP = {
    "SIBILA_DATA_DIR": ("general", "data_dir"),
    "SIBILA_DB_PATH": ("general", "db_path"),
    "SIBILA_LOG_LEVEL": ("general", "log_level"),
    "SIBILA_HMAC_KEY": ("secretos", "hmac_key"),
    "SIBILA_TELEGRAM_TOKEN": ("secretos", "telegram_token"),
    "SIBILA_SMTP_PASSWORD": ("secretos", "smtp_password"),
    "SIBILA_TELEGRAM_CHAT": ("secretos", "telegram_chat"),
    "SIBILA_SMTP_HOST": ("secretos", "smtp_host"),
    "SIBILA_SMTP_USUARIO": ("secretos", "smtp_usuario"),
    "SIBILA_SMTP_PORT": ("secretos", "smtp_puerto"),
    "SIBILA_SMTP_DESTINO": ("secretos", "smtp_destino"),
}


class ConfigError(SibilaError):
    """Configuración inválida: mensaje en español con archivo, clave y causa."""


@dataclass(frozen=True)
class Config:
    data_dir: Path
    db_path: Path
    log_level: str
    secretos: object = field(repr=False)   # MappingProxyType; NUNCA en repr (trampa T4)
    avisos: tuple = ()


def _load_toml(path: Path) -> dict:
    """Lee TOML en binario (tomllib lo exige). BOM → error explícito (verificado:
    tomllib solo dice 'Invalid statement' ante el BOM del Bloc de notas)."""
    with path.open("rb") as f:
        if f.read(3) == b"\xef\xbb\xbf":
            raise ConfigError(
                f"{path.name}: empieza con BOM UTF-8; guárdalo como UTF-8 sin BOM "
                "(el Bloc de notas lo añade)")
        f.seek(0)
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"config inválida en {path.name}: {e}") from e


def _merge(base: dict, encima: dict) -> dict:
    """Merge profundo: el segundo pisa; los dicts anidados se combinan."""
    out = dict(base)
    for k, v in encima.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _apply_env(d: dict) -> None:
    """Las variables SIBILA_* pisan cualquier archivo (spec §2)."""
    for var, (sec, clave) in ENV_MAP.items():
        if os.environ.get(var):  # cadena vacía = no definida (rev. M6: "" anclaría rutas al root)
            d.setdefault(sec, {})[clave] = os.environ[var]


def _validate(d: dict) -> None:
    """Whitelist de secciones/claves (caza typos silenciosos) y tipos."""
    for sec, valores in d.items():
        if sec not in KNOWN:
            raise ConfigError(f"sección desconocida [{sec}] en la configuración")
        for clave, valor in valores.items():
            if clave not in KNOWN[sec]:
                raise ConfigError(
                    f"clave desconocida '{sec}.{clave}' en la configuración; revisa el nombre")
            if sec == "general":
                if clave in ("data_dir", "db_path") and not isinstance(valor, str):
                    raise ConfigError(
                        f"'general.{clave}' debe ser texto (una ruta), no {type(valor).__name__}")
                if clave == "log_level" and (not isinstance(valor, str) or valor not in LOG_LEVELS):
                    raise ConfigError(f"'general.log_level' debe ser una de {sorted(LOG_LEVELS)}")
            if sec == "secretos":
                if clave == "smtp_puerto":
                    # TOML natural escribe `smtp_puerto = 587` (int); una
                    # variable SIBILA_SMTP_PORT llega como texto de dígitos.
                    # Se normaliza a int y se exige rango de puerto real.
                    if isinstance(valor, str) and valor.isascii() and valor.isdigit():
                        valor = int(valor)
                        valores[clave] = valor
                    if isinstance(valor, bool) or not isinstance(valor, int):
                        raise ConfigError(
                            "'secretos.smtp_puerto' debe ser un entero "
                            "(p. ej. 587), no " + type(valor).__name__)
                    if not 1 <= valor <= 65535:
                        raise ConfigError(
                            f"'secretos.smtp_puerto' fuera de rango (1-65535): {valor}")
                elif not isinstance(valor, str):
                    raise ConfigError(f"'secretos.{clave}' debe ser texto")


def _ruta(valor: str, root: Path) -> Path:
    """Rutas relativas ancladas a la raíz del proyecto, NUNCA al cwd (trampa T3)."""
    p = Path(os.path.expandvars(valor)).expanduser()
    return p if p.is_absolute() else (root / p)


def load_config(root: Path | None = None) -> Config:
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    avisos: list[str] = []
    datos = {s: dict(v) for s, v in DEFAULTS.items()}
    p_base = root / "config.toml"
    if p_base.exists():
        base_dict = _load_toml(p_base)
        if "secretos" in base_dict:  # rev. M5: el archivo versionado NO puede tener secretos
            raise ConfigError(
                "config.toml NO puede tener [secretos]: van en config.local.toml "
                "o variables SIBILA_* (spec §3)")
        datos = _merge(datos, base_dict)
    else:
        avisos.append("config.toml no encontrado; usando valores por defecto")
    p_local = root / "config.local.toml"
    if p_local.exists():  # ausente = caso NORMAL (secretos opt-in): silencio
        datos = _merge(datos, _load_toml(p_local))
    _apply_env(datos)
    _validate(datos)
    gen = datos["general"]
    data_dir = _ruta(gen["data_dir"], root)
    db_path = _ruta(gen["db_path"], root) if "db_path" in gen else data_dir / "sibila.db"
    return Config(
        data_dir=data_dir,
        db_path=db_path,
        log_level=gen["log_level"],
        secretos=MappingProxyType(dict(datos.get("secretos", {}))),
        avisos=tuple(avisos),
    )

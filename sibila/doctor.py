"""`sibila doctor` — comprobación post-instalación del PAQUETE COMPLETO (T2,
D-048). Distinto de `check` (contrato congelado: BD/schema/git/ots, puerta
VERDE del instalador): doctor audita deps importables, recursos de datos con
SHA-256, data_dir escribible, git/ots y secretos.

Contrato (plan T2 §3):
- D1 BD existe, abre y verify_schema sin problemas → FALLO si no (la línea
  lleva el literal "12 tablas", asertado por test — lección M1-residual B2).
- D2 deps vía importlib.util.find_spec (SIN importar lo pesado): feedparser,
  requests, sgmllib, fasttext (módulo de fasttext-predict, A7/H1),
  vaderSentiment → FALLO si falta cualquiera. lingua → AVISO ("fallback de
  idioma desactivado"; "(skip explícito)" si existe el centinela
  <data_dir>/recursos/SIN_LINGUA del opt-out SIBILA_SIN_LINGUA).
- D3 recursos en <data_dir>/recursos/ (vía config.load_config, NUNCA ruta
  fija): lid.176.ftz + 4 NRC. SHA-256 verificado contra
  emocion.SHA256_ESPERADOS (NRC) y tools/descargar_recursos.SHA256_LID176
  (lid.176.ftz; rev. Dijkstra M1); dict NRC vacío → FALLO "hashes no
  fijados: instalación no verificable"; ausentes → AVISO "modo degradado"
  (A5), no FALLO. Hash malo → FALLO.
- D4 data_dir escribible (sonda con pid) → FALLO si no.
- D5 git y ots → AVISO, nunca FALLO (TP-N1).
- D6 config.local.toml con hmac_key → AVISO si falta (author_hash NULL),
  nunca FALLO.
- Resumen "doctor: SANO (n avisos)" / "doctor: ROTO (n fallos)".
- CERO escritura en BD: conexión SQLite mode=ro (la única escritura es la
  sonda temporal en data_dir, como en check).
"""
import hashlib
import importlib.util
import os
import sqlite3
import shutil
from pathlib import Path

DEPS_DURAS = ("feedparser", "requests", "sgmllib", "fasttext", "vaderSentiment")
RECURSOS = ("lid.176.ftz", "nrc_vad_en.txt", "nrc_vad_es.txt",
            "nrc_emociones_en.txt", "nrc_emociones_es.txt")
CENTINELA_LINGUA = "SIN_LINGUA"


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def _dep(nombre: str) -> bool:
    """find_spec sin ejecutar el módulo (lo pesado no se importa)."""
    try:
        return importlib.util.find_spec(nombre) is not None
    except (ImportError, ValueError):
        return False


def _sha256_lid176() -> "str | None":
    """Hash fijado de lid.176.ftz: vive en tools/descargar_recursos.py (que
    viaja con el paquete; rev. Dijkstra M1). None si tools/ no es importable
    (layout roto — se reporta como FALLO de verificabilidad)."""
    try:
        from tools.descargar_recursos import SHA256_LID176
        return SHA256_LID176
    except ImportError:
        return None


def doctor(cfg) -> tuple[int, int, list]:
    """Ejecuta las comprobaciones D1-D6. Devuelve (fallos, avisos, líneas)
    donde líneas son (estado, mensaje) con estado ∈ OK/AVISO/FALLO.
    NUNCA lanza por comprobación fallida: todo se reporta."""
    lineas: list = []
    fallos = avisos = 0

    def marca(estado: str, msg: str) -> None:
        nonlocal fallos, avisos
        lineas.append((estado, msg))
        if estado == "FALLO":
            fallos += 1
        elif estado == "AVISO":
            avisos += 1

    # D1 — BD: existe, abre (mode=ro), schema íntegro
    from . import db
    if not cfg.db_path.is_file():
        marca("FALLO", f"base de datos ausente: {cfg.db_path} (corre init)")
    else:
        try:
            # as_uri(): la ruta va ESCAPADA — una ruta con '#' o espacios
            # rompería el URI plano y abriría OTRO fichero vacío (rev. B1)
            uri = cfg.db_path.resolve().as_uri() + "?mode=ro"
            con = sqlite3.connect(uri, uri=True)
            try:
                problemas = db.verify_schema(con)
            finally:
                con.close()
            if problemas:
                marca("FALLO", f"schema: {'; '.join(problemas)}")
            else:
                marca("OK", "base de datos íntegra (12 tablas)")
        except (sqlite3.Error, OSError) as e:
            marca("FALLO", f"base de datos no abre: {e}")

    # D2 — dependencias importables (sonda find_spec)
    for dep in DEPS_DURAS:
        if _dep(dep):
            marca("OK", f"dep importable: {dep}")
        else:
            marca("FALLO", f"dep NO importable: {dep} "
                           "(re-ejecuta instalar.bat)")
    centinela = cfg.data_dir / "recursos" / CENTINELA_LINGUA
    if _dep("lingua"):
        marca("OK", "dep importable: lingua")
    elif centinela.is_file():
        marca("AVISO", "lingua: no instalado (skip explícito SIBILA_SIN_LINGUA)")
    else:
        marca("AVISO", "lingua: no instalado; fallback de idioma desactivado")

    # D3 — recursos de datos con SHA-256
    from .procesado import emocion
    rec_dir = cfg.data_dir / "recursos"
    if not emocion.SHA256_ESPERADOS:
        marca("FALLO", "hashes no fijados: instalación no verificable "
                       "(SHA256_ESPERADOS vacío)")
    for nombre in RECURSOS:
        ruta = rec_dir / nombre
        if not ruta.is_file():
            marca("AVISO", f"recurso ausente: {nombre} (modo degradado; "
                           "corre tools\\descargar_recursos.py)")
            continue
        esperado = emocion.SHA256_ESPERADOS.get(nombre)
        if esperado is None and nombre == "lid.176.ftz":
            # M1: el hash de lid.176.ftz está fijado en tools/ (viaja);
            # si tools/ no importa, el layout está roto → FALLO de
            # verificabilidad, NUNCA el OK genérico (rev. Hamilton T2R2-1:
            # falla-CERRADA, no abierta)
            esperado = _sha256_lid176()
            if esperado is None:
                marca("FALLO", f"recurso {nombre}: tools/ no importable; "
                               "hash NO verificable (layout roto)")
                continue
        if esperado is None:
            marca("OK", f"recurso presente: {nombre} (sin hash fijado; "
                        "no aplica verificación)")
        elif _sha256(ruta) == esperado:
            marca("OK", f"recurso verificado: {nombre}")
        else:
            marca("FALLO", f"SHA-256 no coincide: {nombre} "
                           "(borra el fichero y re-descarga)")

    # D4 — data_dir escribible (sonda con pid, patrón consolidado de check)
    try:
        sonda = cfg.data_dir / f".doctor_sonda_{os.getpid()}"
        sonda.write_text("ok", encoding="ascii")
        sonda.unlink()
        marca("OK", "data_dir escribible")
    except OSError as e:
        marca("FALLO", f"data_dir no escribible: {e}")

    # D5 — git y ots: AVISO, nunca FALLO (TP-N1)
    git_ok, ots_ok = shutil.which("git"), shutil.which("ots")
    marca("OK" if git_ok else "AVISO",
          "git disponible (anclaje del registro)" if git_ok
          else "git no encontrado: anclaje quedará pendiente")
    marca("OK" if ots_ok else "AVISO",
          "ots disponible" if ots_ok
          else "ots no encontrado: sello ots desactivado")

    # D6 — config.local.toml con hmac_key: AVISO, nunca FALLO
    if (cfg.secretos or {}).get("hmac_key"):
        marca("OK", "hmac_key presente (config.local.toml)")
    else:
        marca("AVISO", "sin hmac_key: author_hash quedará NULL "
                       "(genera config.local.toml re-instalando)")
    return fallos, avisos, lineas


def resumen(fallos: int, avisos: int) -> str:
    if fallos:
        return f"doctor: ROTO ({fallos} fallos)"
    return f"doctor: SANO ({avisos} avisos)"

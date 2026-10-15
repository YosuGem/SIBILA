"""Anclaje git/ots del registro sellado (`sibila registro anclar`, Bloque 6).

Envoltorio de subprocess: NO es puro. Reglas:
- argv en LISTA, jamás shell=True (trampa Hopper: rutas con espacios/acentos).
- git/ots ausentes → degradación a "pendiente" con AVISO y exit 0 (TP-N1
  admite anclaje pendiente); NO hay `ots verify`: el sello ots queda
  pendiente (degradación documentada, rev. Dijkstra M3); subprocess siempre
  con timeout 30 s, nunca cuelgue.
- Nada de esto toca la BD salvo ops_metrics registro.anclajes (tx corta propia,
  DESPUÉS del commit: aquí no hay cadena que proteger).
- El repo git es INTERNO de registro/ (git init perezoso): el anclaje no
  depende de que data_dir esté dentro de un repo (D-B6-02).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from . import SibilaError, db

log = logging.getLogger("sibila.anclaje")

TIMEOUT = 30          # s; git local es inmediato, ots puede necesitar red
FICHERO = "predicciones.jsonl"


class AnclajeError(SibilaError):
    """Fallo inesperado de git (repo corrupto, permisos…): visible, no trago.
    Hereda de SibilaError: la CLI lo muestra accionable, jamás traceback
    desnudo (rev. Dijkstra M3)."""


def _git():
    return shutil.which("git")


def _ots():
    return shutil.which("ots")


def _run(argv, cwd=None, captura=True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=captura, text=True,
                              timeout=TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise AnclajeError(f"timeout ({TIMEOUT} s) en {' '.join(argv[:2])}") from e


def _git_ok(repo: Path, *args) -> subprocess.CompletedProcess:
    cp = _run([_git(), "-C", str(repo), *args])
    if cp.returncode != 0:
        raise AnclajeError(f"git {' '.join(args)}: {cp.stderr.strip()}")
    return cp


def _n_lineas(ruta: Path) -> int:
    if not ruta.exists():
        return 0
    datos = ruta.read_bytes()
    return sum(1 for t in datos.split(b"\n") if t)


def _ultimo_hash(ruta: Path) -> str:
    import json
    if not ruta.exists():
        return "0" * 64
    trozos = [t for t in ruta.read_bytes().split(b"\n") if t]
    if not trozos:
        return "0" * 64
    try:
        return json.loads(trozos[-1]).get("hash", "0" * 64)
    except ValueError:  # cola coja: no es materia del anclaje
        return "0" * 64


def anclar(cfg, con) -> dict:
    """Ancla el JSONL en el git interno de registro/ (+ ots si existe).
    Devuelve {anclado, aviso, commit, n_lineas}; métrica registro.anclajes."""
    ruta_dir = Path(cfg.data_dir) / "registro"
    ruta_dir.mkdir(parents=True, exist_ok=True)
    fichero = ruta_dir / FICHERO
    res = {"anclado": False, "aviso": None, "commit": None,
           "n_lineas": _n_lineas(fichero)}
    # D-078 (segunda prueba Windows): sin señales selladas aún no hay JSONL;
    # "nada que anclar" NO es un fallo (un pipeline diario en día sin señales
    # no puede terminar en ROJO). Mismo criterio que "anclaje: sin cambios".
    if res["n_lineas"] == 0:
        res["aviso"] = "anclaje: sin señales selladas que anclar"
        _metrica(con, 0)
        return res
    if not _git():
        res["aviso"] = "git no encontrado: anclaje pendiente"
        _metrica(con, 0)
        return res
    if not (ruta_dir / ".git").exists():
        _git_ok(ruta_dir, "init", "-q")
    _git_ok(ruta_dir, "add", "--", FICHERO)
    # diff --cached --quiet: 0 = sin cambios → commit vacío prohibido (trampa 10)
    cp = _run([_git(), "-C", str(ruta_dir), "diff", "--cached", "--quiet",
               "--", FICHERO])
    if cp.returncode == 0:
        _metrica(con, 1)
        res["anclado"] = True
        res["aviso"] = "anclaje: sin cambios"
        return res
    cp = _run([_git(), "-C", str(ruta_dir), "-c", "user.name=sibila",
               "-c", "user.email=sibila@localhost", "commit", "-q", "-m",
               f"anclaje {res['n_lineas']} líneas {_ultimo_hash(fichero)}",
               "--", FICHERO])
    if cp.returncode != 0:
        raise AnclajeError(f"git commit: {cp.stderr.strip()}")
    res["commit"] = _git_ok(ruta_dir, "rev-parse", "HEAD").stdout.strip()
    if _ots():  # .ots junto al JSONL; verify diferido a verificar (red, timeout)
        sello = ruta_dir / "ultimo_commit.txt"
        sello.write_text(res["commit"] + "\n", encoding="ascii")
        cp = _run([_ots(), "stamp", str(sello)])
        if cp.returncode != 0:
            res["aviso"] = f"ots stamp falló ({cp.stderr.strip()}): anclaje ots pendiente"
    else:
        res["aviso"] = "ots no encontrado: anclaje ots pendiente (requirements-extra)"
    res["anclado"] = True
    _metrica(con, 1)
    return res


def estado_anclaje(ruta_dir: Path) -> str:
    """Estado del anclaje SIN escribir (lo usa verificar): 'sin git' /
    'pendiente' (sin repo, sin commits o fichero distinto del HEAD) /
    'anclado' (el HEAD contiene el fichero exacto). ots: NUNCA se verifica
    aquí (no hay `ots verify` implantado; el sello ots queda en degradación
    documentada a 'pendiente' hasta que exista — rev. Dijkstra M3)."""
    if not _git():
        return "sin git"
    if not (Path(ruta_dir) / ".git").exists():
        return "pendiente"
    cp = _run([_git(), "-C", str(ruta_dir), "rev-parse", "--verify", "-q", "HEAD"])
    if cp.returncode != 0:
        return "pendiente"
    cp = _run([_git(), "-C", str(ruta_dir), "diff", "--quiet", "HEAD", "--", FICHERO])
    if cp.returncode != 0:
        return "pendiente"
    cp = _run([_git(), "-C", str(ruta_dir), "status", "--porcelain", "--", FICHERO])
    if cp.stdout.strip():
        return "pendiente"
    return "anclado"


def _metrica(con, valor: float) -> None:
    """Tx corta propia, DESPUÉS del commit (no hay cadena que proteger)."""
    with db.tx(con):
        con.execute("INSERT INTO ops_metrics(ts, clave, valor) VALUES (?, ?, ?)",
                    (db.now_iso(), "registro.anclajes", valor))

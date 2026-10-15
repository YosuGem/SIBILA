"""Manifiesto SHA-256 del paquete (`sibila paquete {generar,verificar}`, T2/D-048).

Inventario determinista del árbol del paquete + MANIFIESTO.sha256.json
serializado con el `canonical_json` CONGELADO de sibila/registro/canonico.py
TAL CUAL (sin variantes — lección D-030: ningún formato nuevo de
serialización). Lista de ficheros ordenada por ruta POSIX (`as_posix`,
sorted por bytes), hash sobre BYTES crudos (los .bat viajan en CRLF: un
editor que los pase a LF produce rotura REAL — es lo deseado, §1.4b).

Exclusiones CERRADAS (H1, §1.4/§2.2): un árbol VIVIDO (destino con días de
uso) nace con secretos, BD, registro y logs; cubrirlos produciría roturas
espurias y — peor — filtraría los secretos de config.local.toml a un fichero
de hashes distribuible (test §2.4.10 con mordida). Ficheros EXTRA en destino
NO son rotura (§2.2).

Versionado (D-019): NO existe versión del programa en código. SCHEMA_VERSION
(PRAGMA user_version), INFORME_VERSION (render) y BOT_VERSION/STOPWORDS_VERSION
(algoritmos) NO son la versión del programa. `VERSION_PROGRAMA = None` es la
única fuente que el generador vuelca al manifiesto; la asigna solo Yosu.
`generado` (ISO UTC) da la cronología interna sin violar D-019.

Stdlib puro + sibila.registro.canonico (guardián AST de empaquetado).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .registro.canonico import canonical_json   # CONGELADO: se usa TAL CUAL

# --- Exclusión CERRADA (§1.4/§2.2 corregida) -------------------------------
DIR_EXCLUIDOS_RAIZ = ("logs", "datos", "registro")   # solo a nivel raíz: el
# paquete `sibila/registro/` es CÓDIGO y viaja (la exclusión es del JSONL de
# destino); `__pycache__` y `.pytest_cache` se excluyen como componente a
# cualquier profundidad (D-077: .pytest_cache ensuciaba el manifiesto tras
# cada corrida de la batería)
SUFIJOS_EXCLUIDOS = (".pyc", ".db", ".db-wal", ".db-shm")
NOMBRES_EXCLUIDOS = (".gitignore",
                     "MANIFIESTO.sha256.json",  # autoexclusión (§2.1)
                     # artefactos que genera el instalador EN DESTINO (D-077):
                     # nunca deben entrar en el manifiesto si se regenera
                     # sobre una carpeta ya instalada
                     "requirements-nucleo.txt",
                     "tarea_ingesta.final.xml",
                     "tarea_diaria.final.xml")
# SECRETOS NUNCA (§2.4.10; rev. Dijkstra M4): por PREFIJO, no por nombre
# exacto — `config.local.toml` y variantes tipo `.bak`/`.tmp` (una copia de
# respaldo con credenciales jamás cuela en el manifiesto); la plantilla
# `config.local.toml.example` SÍ viaja (§1.2: no contiene secretos).
SECRETOS_PREFIJO = "config.local.toml"
SECRETOS_EXCEPCION = "config.local.toml.example"

MANIFIESTO = "MANIFIESTO.sha256.json"
GENERADOR = "sibila-paquete-1"   # versión del ALGORITMO del manifiesto
VERSION_PROGRAMA = None          # la asigna solo Yosu (D-019); no es
                                 # SCHEMA_VERSION ni INFORME_VERSION


def _excluido(rel: Path) -> bool:
    """True si la ruta relativa cae en la exclusión cerrada (datos de destino
    a nivel raíz, __pycache__/.pytest_cache a cualquier profundidad, sufijo
    o nombre). Secretos por PREFIJO (M4): config.local.toml* fuera salvo la
    plantilla."""
    if rel.parts and rel.parts[0] in DIR_EXCLUIDOS_RAIZ:
        return True
    if "__pycache__" in rel.parts or ".pytest_cache" in rel.parts:
        return True
    if rel.name.startswith(SECRETOS_PREFIJO) and rel.name != SECRETOS_EXCEPCION:
        return True
    if rel.name in NOMBRES_EXCLUIDOS:
        return True
    return rel.name.endswith(SUFIJOS_EXCLUIDOS)


def inventario(raiz: Path) -> "list[Path]":
    """Ficheros del paquete (rutas relativas), orden POSIX determinista
    (NUNCA orden del filesystem). Determinista por construcción."""
    raiz = Path(raiz)
    salida = []
    for p in raiz.rglob("*"):
        if p.is_file():
            rel = p.relative_to(raiz)
            if not _excluido(rel):
                salida.append(rel)
    return sorted(salida, key=lambda r: r.as_posix())


def generar(raiz: Path, *, ahora=None) -> bytes:
    """Manifiesto como canonical_json(objeto) + b"\\n" (convención del
    registro sellado). `ahora` inyectable (H4: determinismo testeable);
    None → reloj real UTC. Con el mismo árbol y el mismo `ahora`, los bytes
    son IDÉNTICOS entre máquinas."""
    if ahora is None:
        generado = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif isinstance(ahora, datetime):
        generado = ahora.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        generado = str(ahora)
    raiz = Path(raiz)
    ficheros = []
    for rel in inventario(raiz):
        datos = (raiz / rel).read_bytes()           # bytes crudos (CRLF y todo)
        ficheros.append({"bytes": len(datos),
                         "ruta": rel.as_posix(),
                         "sha256": hashlib.sha256(datos).hexdigest()})
    objeto = {"ficheros": ficheros,
              "generado": generado,
              "generador": GENERADOR,
              "version_programa": VERSION_PROGRAMA}
    return canonical_json(objeto) + b"\n"


def escribir(raiz: Path, *, ahora=None) -> Path:
    """generar + write_bytes + fsync (misma doctrina de disco que sella)."""
    raiz = Path(raiz)
    ruta = raiz / MANIFIESTO
    datos = generar(raiz, ahora=ahora)
    with ruta.open("wb") as f:
        f.write(datos)
        f.flush()
        os.fsync(f.fileno())
    return ruta


def verificar(raiz: Path) -> "list[str]":
    """[] = ÍNTEGRO; si no, TODAS las roturas en orden de ruta (doctrina
    registro/verificar: nunca return-early). Clases: `falta:`, `hash:`,
    `bytes:` (bytes se reporta ADEMÁS de hash si ambos difieren — más
    evidencia, nunca menos). Los extra del destino no son rotura (§2.2)."""
    raiz = Path(raiz)
    ruta = raiz / MANIFIESTO
    if not ruta.exists():
        return [f"falta: {MANIFIESTO}"]
    objeto = json.loads(ruta.read_bytes())          # canonical_json es JSON
    roturas = []
    for entrada in objeto["ficheros"]:
        rel = entrada["ruta"]
        f = raiz / rel
        if not f.is_file():
            roturas.append(f"falta: {rel}")
            continue
        datos = f.read_bytes()
        if len(datos) != entrada["bytes"]:
            roturas.append(f"bytes: {rel}")         # además de hash (§2.2)
        if hashlib.sha256(datos).hexdigest() != entrada["sha256"]:
            roturas.append(f"hash: {rel}")
    return roturas

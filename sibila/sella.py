"""Capa de datos del registro sellado (`sibila registro`, Bloque 6).

ÚNICO módulo del bloque que toca BD y fichero JSONL (D-B6-01: CERO tablas
nuevas — `predictions` ya existe; el directorio `registro/` vive en data_dir,
D-B6-02). La criptografía de la cadena, la derivación de borradores y la
verificación pura viven en `sibila/registro/` (capa pura, contrato §3).

Reglas de oro:
- UNA tx BEGIN IMMEDIATE POR DÍA (D-B6-03); el append del JSONL va DENTRO de la
  tx (prev_hash es sección crítica, trampa 1) y ANTES que la fila (el fichero
  es la fuente de verdad de la cadena, spec §8): append+flush+fsync → INSERT.
- Append en BINARIO 'ab' con canonical_json(linea)+b"\\n" (trampa 3: CRLF jamás).
- Dedup por clave lógica (tema, metrica, umbral, ventana, criterio_acierto)
  SOLO contra pendientes NO vencidas (B1 ratificada; vencida() es de la pura).
- Reconciliación SENTIDO ÚNICO fichero→tabla, con dos guardas: madura se
  computa por el created_at DE LA LÍNEA (M2 Turing) y solo corre si no hay
  estados no-pendientes (gate M2; si los hay → AVISO y no se toca nada).
- Cola coja (última línea sin \\n final): sellar NO hace append → SellaError +
  exit 1. INTERVENCIÓN MANUAL documentada: recortar la cola coja es la ÚNICA
  edición autorizada del JSONL, y solo del tramo final no confirmado por fsync
  (alternativa: restaurar desde el último anclaje git). Append-only se precisa
  como "append-only salvo cola truncada por crash, con procedimiento".
- El reloj es parámetro (`ahora`); nada de datetime.now() aquí dentro.
- Mi capa NO reimplanta canonical_json, hashes ni validaciones de formato:
  los importa de la capa pura (trampa 2/M4: prohibido regex propio de ventana).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from . import SibilaError, db

log = logging.getLogger("sibila.sella")

GENESIS = "0" * 64                    # prev_hash de la primera línea (spec §8)
DIAS_MADUREZ = 28                     # misma definición que detecta (D-041)

CLAVES_METRICAS = ("selladas", "inmaduras", "omitidas", "reconciliadas",
                   "lineas_total")

# Campos de la clave lógica de dedup (§2; created_at y hash JAMÁS, trampa 7)
CLAVE = ("tema", "metrica", "umbral", "ventana", "criterio_acierto")
CAMPOS_LINEA = CLAVE + ("created_at", "prev_hash", "hash")


class SellaError(SibilaError):
    """Fallo previsto del registro (BD, cola coja, rechazo de la capa pura)."""


def _capa(capa=None):
    """Resuelve la capa pura (contrato §3): inyectada en tests o real de
    sibila/registro (import perezoso). Objeto con: canonical_json, Senal,
    derivar, construir_linea, hash_linea, verificar_lineas, vencida."""
    if capa is not None:
        return capa
    from .registro import canonico, derivar, sellar, verificar
    from types import SimpleNamespace
    return SimpleNamespace(
        canonical_json=canonico.canonical_json,
        Senal=derivar.Senal,
        derivar=derivar.derivar,
        construir_linea=sellar.construir_linea,
        hash_linea=sellar.hash_linea,
        verificar_lineas=verificar.verificar_lineas,
        # vencida: el colega la ubicó en verificar.py (§3 permite la ubicación)
        vencida=getattr(derivar, "vencida", None) or verificar.vencida,
    )


def registro_dir(cfg) -> Path:
    """data_dir/registro/, creado perezosamente (BD de instalación anterior)."""
    ruta = Path(cfg.data_dir) / "registro"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _fichero(cfg) -> Path:
    return registro_dir(cfg) / "predicciones.jsonl"


def _leer_lineas(ruta: Path) -> "tuple[list[dict], list[bytes], bool]":
    """(líneas parseadas, trozos crudos, cola_coja). Lectura binaria; json.loads
    directo de bytes (trampa 12/T8). La cola coja NO se parsea: se reporta.
    Solo se descarta el trozo FINAL vacío (el \\n de cierre): una línea en
    blanco INTERIOR o JSON inválido es manipulación/corrupción → ValueError
    con línea y causa (rev. Hamilton M1 / Dijkstra M1); sellar lo convierte en
    SellaError (fichero) y verificar lo cuenta como rotura."""
    if not ruta.exists():
        return [], [], False
    datos = ruta.read_bytes()
    if not datos:
        return [], [], False
    coja = not datos.endswith(b"\n")
    trozos = datos.split(b"\n")
    if trozos and trozos[-1] == b"":
        trozos = trozos[:-1]                 # solo el \n final
    if coja:
        trozos = trozos[:-1]                 # cola coja: no se parsea
    lineas = []
    for i, t in enumerate(trozos, 1):
        if not t:
            raise ValueError(f"línea {i}: vacía (¿edición manual del JSONL?)")
        try:
            lineas.append(json.loads(t))
        except ValueError as e:
            raise ValueError(f"línea {i}: JSON inválido ({e})") from e
    return lineas, trozos, coja


def _dias_historia(con, dia_txt: str) -> int:
    """Días de calendario desde el primer día con stats (definición D-041)."""
    primero = None
    for tabla in ("term_stats", "emo_stats"):
        r = con.execute(f"SELECT MIN(day) FROM {tabla}").fetchone()[0]
        if r is not None:
            primero = r if primero is None else min(primero, r)
    if primero is None:
        return 0
    return (date.fromisoformat(dia_txt) - date.fromisoformat(primero)).days


def _senales_del_dia(con, dia: str, capa) -> list:
    """Senales candidatas del día (confirmado+inmaduro — trampa 13: las
    inmaduras TAMBIÉN se sellan, son las madura=0 del gate G1), unidas a terms
    para el texto del target, ordenadas por (day, target_type, target, metric)
    — la ordenación es responsabilidad de datos (§3)."""
    filas = con.execute(
        "SELECT s.day, s.target_type, s.metric, s.score, s.status, t.text AS target"
        " FROM signals s JOIN terms t ON t.id = s.target_id"
        " WHERE s.day = ? AND s.status IN ('confirmado', 'inmaduro')"
        " ORDER BY s.day, s.target_type, t.text, s.metric", (dia,)).fetchall()
    from decimal import Decimal
    return [capa.Senal(target_type=f["target_type"], target=f["target"],
                       metric=f["metric"], score=Decimal(str(f["score"])),
                       status=f["status"], day=f["day"]) for f in filas]


def _pendientes_no_vencidas(con, dia: str, capa) -> set:
    """Claves lógicas pendientes y NO vencidas a fecha `dia` (B1 ratificada:
    el vencimiento lo decide vencida() de la capa pura, nunca SQL).
    `dia` llega como str ISO y vencida() exige `date` (contrato D-T6-4):
    conversión AQUÍ (rev. Dijkstra B1 / Hamilton N1 — el choque de tipos
    rompía la dedup desde la 2ª ejecución)."""
    out = set()
    d = date.fromisoformat(dia)
    for r in con.execute(
            "SELECT tema, metrica, umbral, ventana, criterio_acierto, created_at"
            " FROM predictions WHERE estado = 'pendiente'"):
        if not capa.vencida(r["created_at"], r["ventana"], d):
            out.add(tuple(r[c] for c in CLAVE))
    return out


def _insertar_prediccion(con, linea: dict, madura: int) -> None:
    con.execute(
        "INSERT INTO predictions(tema, metrica, umbral, ventana, criterio_acierto,"
        " created_at, prev_hash, hash, estado, madura) VALUES"
        " (?, ?, ?, ?, ?, ?, ?, ?, 'pendiente', ?)",
        tuple(linea[c] for c in CAMPOS_LINEA) + (madura,))


def _append_linea(fichero: Path, linea: dict, capa) -> None:
    """Append BINARIO + flush + fsync ANTES del INSERT (trampas 3 y 5)."""
    with fichero.open("ab") as f:
        f.write(capa.canonical_json(linea) + b"\n")
        f.flush()
        os.fsync(f.fileno())


def sellar_dia(con, cfg, dia: str, *, capa, ahora: str, claves_vivas: set) -> dict:
    """Sella las señales de UN día en UNA tx (D-B6-03). Devuelve contadores.
    `claves_vivas` es el conjunto de dedup compartido por el rango (M4:
    multi-día, el mismo tema dos días seguidos se omite la 2ª vez)."""
    cont = {k: 0 for k in CLAVES_METRICAS}
    fichero = _fichero(cfg)
    senales = _senales_del_dia(con, dia, capa)
    madura = 1 if _dias_historia(con, dia) >= DIAS_MADUREZ else 0
    # FASE CPU fuera de tx: derivar (pura) + dedup por clave lógica
    borradores = []
    for b in capa.derivar(tuple(senales), date.fromisoformat(dia)):
        clave = tuple(getattr(b, c) for c in CLAVE)
        if clave in claves_vivas:
            cont["omitidas"] += 1
            continue
        claves_vivas.add(clave)
        borradores.append(b)
    # FASE ESCRITURA (UNA tx por día): la lectura del último hash y el append
    # van DENTRO del BEGIN IMMEDIATE (trampa 1: prev_hash es sección crítica).
    with db.tx(con):
        try:
            lineas, _crudos, coja = _leer_lineas(fichero)
        except ValueError as e:  # fichero corrupto/manipulado (rev. M1)
            raise SellaError(
                f"registro: fichero JSONL ilegible ({e}); intervención manual "
                "requerida (¿manipulación? restaura desde el último anclaje git)"
            ) from e
        if coja:
            raise SellaError(
                "registro: última línea incompleta (crash previo); intervención "
                "manual requerida: recorta la cola coja (única edición autorizada) "
                "o restaura desde el último anclaje git")
        prev_hash = lineas[-1]["hash"] if lineas else GENESIS
        # Reconciliación fichero→tabla (sentido único, §4.1) con sus dos guardas
        hashes_tabla = {r[0] for r in con.execute("SELECT hash FROM predictions")}
        huerfanas = [l for l in lineas if l["hash"] not in hashes_tabla]
        if huerfanas:
            n_no_pend = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE estado != 'pendiente'"
            ).fetchone()[0]
            if n_no_pend:  # gate M2: no resucitar resueltas como pendientes
                cont["aviso_reconciliacion"] = True
            else:
                reconciliadas_claves = set()
                for l in huerfanas:  # madura por created_at DE LA LÍNEA (M2 Turing)
                    m = 1 if _dias_historia(con, l["created_at"][:10]) >= DIAS_MADUREZ else 0
                    _insertar_prediccion(con, l, m)
                    cont["reconciliadas"] += 1
                    reconciliadas_claves.add(tuple(l[c] for c in CLAVE))
                # CC-T1-3 (I8): la dedup de borradores ocurrió ANTES (fase CPU)
                # que la reconciliación (dentro de la tx): el borrador
                # equivalente a una línea huérfana se FILTRA aquí (el crash
                # multi-borrador termina 2 líneas, no 3) y la clave queda viva.
                claves_vivas |= reconciliadas_claves
                antes = len(borradores)
                borradores = [b for b in borradores
                              if tuple(getattr(b, c) for c in CLAVE)
                              not in reconciliadas_claves]
                cont["omitidas"] += antes - len(borradores)
        for b in borradores:
            linea = capa.construir_linea(b, ahora, prev_hash)  # ValueError → fuera
            prev_hash = linea["hash"]
            _append_linea(fichero, linea, capa)     # fichero ANTES que fila
            _insertar_prediccion(con, linea, madura)
        cont["selladas"] = len(borradores)
        cont["inmaduras"] = len(borradores) if madura == 0 else 0
        cont["lineas_total"] = len(lineas) + len(borradores)
        ts = db.now_iso()
        for clave in CLAVES_METRICAS:
            con.execute("INSERT INTO ops_metrics(ts, clave, valor) VALUES (?, ?, ?)",
                        (ts, f"registro.{clave}", float(cont[clave])))
    return cont


def ejecutar(cfg, con, *, desde=None, hasta=None, dia=None, ahora=None,
             capa=None) -> dict:
    """Una ejecución de sellar sobre el rango (UNA tx por día). `ahora`:
    datetime inyectable; created_at = 'YYYY-MM-DDTHH:MM:SSZ' (db.now_iso() ya
    produce ese formato). Devuelve contadores y avisos para el CLI."""
    capa = _capa(capa)
    if ahora is None:
        ahora_txt = db.now_iso()
        hoy = date.fromisoformat(ahora_txt[:10])
    else:
        ahora_txt = ahora.strftime("%Y-%m-%dT%H:%M:%SZ")
        hoy = ahora.date()
    ayer = (hoy - _un_dia()).isoformat()
    if dia is not None:
        ini = fin = dia
    elif desde is not None:
        ini, fin = desde, hasta or ayer
    else:
        ini = fin = ayer
    dias = _rango(ini, fin)
    avisos: list = []
    total = {k: 0 for k in CLAVES_METRICAS}
    claves_vivas: set = set()
    for d in dias:
        claves_vivas |= _pendientes_no_vencidas(con, d, capa)
        try:
            cont = sellar_dia(con, cfg, d, capa=capa, ahora=ahora_txt,
                              claves_vivas=claves_vivas)
        except ValueError as e:  # la pura rechaza formato (ventana, etc.): visible
            raise SellaError(f"la capa pura rechazó un borrador del día {d}: {e}") from e
        except sqlite3.Error as e:
            raise SellaError(f"registro día {d}: {e}") from e
        if cont.pop("aviso_reconciliacion", False):
            avisos.append("reconciliación manual requerida: hay predicciones con "
                          "estado no pendiente y líneas sin fila")
        for k in CLAVES_METRICAS:
            total[k] += cont[k]
    try:
        total["lineas_total"] = len(_leer_lineas(_fichero(cfg))[0])
    except ValueError as e:
        raise SellaError(f"registro: fichero JSONL ilegible ({e})") from e
    return {"contadores": total, "avisos": avisos, "dias": dias}


def _un_dia():
    from datetime import timedelta
    return timedelta(days=1)


def _rango(ini: str, fin: str) -> list:
    from datetime import timedelta
    a, b = date.fromisoformat(ini), date.fromisoformat(fin)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def verificar(cfg, con, *, capa=None, anclaje=None) -> dict:
    """Verificación de datos: cadena pura + cruce fichero↔tabla en AMBOS
    sentidos (trampa 8) + estado del anclaje (lo rellena anclaje.py por
    subprocess). Nivel de amenaza declarado: detecta manipulación casual y
    restauraciones parciales; contra un atacante que recompute la cadena, rehaga
    los commits y falsifique ots está el anclaje externo (spec §8)."""
    capa = _capa(capa)
    if anclaje is None:
        from . import anclaje as anclaje_mod
        anclaje = anclaje_mod
    fichero = _fichero(cfg)
    try:
        lineas, crudos, coja = _leer_lineas(fichero)
        roturas_lectura: list = []
    except ValueError as e:
        # Fichero ilegible (línea vacía interior / JSON inválido): se reporta
        # como rotura localizada con línea y causa (rev. Dijkstra M1) y se
        # sigue con lo parseable de la tabla (cruce fichero↔tabla vacío).
        lineas, crudos, coja = [], [], False
        roturas_lectura = [str(e)]
    resultado = capa.verificar_lineas(tuple(lineas))
    roturas = roturas_lectura + list(resultado.roturas)
    # Byte-exactitud: la línea cruda debe ser canonical_json(linea) — una
    # reescritura CRLF o reformateo rompe la cadena aunque el JSON parsee (T3).
    for i, (l, crudo) in enumerate(zip(lineas, crudos), 1):
        if capa.canonical_json(l) != crudo:
            roturas.append(f"línea {i}: bytes no canónicos (¿CRLF o reformateo?)")
    filas = con.execute(
        "SELECT tema, metrica, umbral, ventana, criterio_acierto, created_at,"
        " prev_hash, hash FROM predictions ORDER BY id ASC").fetchall()
    # Cruce posicional (orden de inserción = orden de cadena)
    for i, l in enumerate(lineas):
        if i >= len(filas):
            roturas.append(f"línea {i + 1} sin fila en predictions "
                           f"(hash {l['hash'][:8]}…; reconciliable con sellar)")
            continue
        f = filas[i]
        for c in CAMPOS_LINEA:
            if str(f[c]) != str(l[c]):
                roturas.append(f"línea {i + 1}: campo {c} diverge "
                               f"(fichero {l[c]!r} ≠ tabla {f[c]!r})")
    for i in range(len(lineas), len(filas)):
        roturas.append(f"fila {i + 1} de predictions sin línea en el fichero "
                       f"(hash {str(filas[i]['hash'])[:8]}…): escritura a mano")
    estado_anclaje = anclaje.estado_anclaje(registro_dir(cfg))
    return {"ok": resultado.ok and not roturas, "n_lineas": len(lineas),
            "roturas": tuple(roturas), "cola_coja": coja,
            "anclaje": estado_anclaje,
            "ultimo_hash": lineas[-1]["hash"] if lineas else None}

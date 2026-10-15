"""Interfaz de línea de comandos (argparse stdlib, cero lógica de negocio, spec §2).

Exit codes: 0 = OK · 1 = fallo de ejecución o check ROJO · 2 = uso incorrecto (argparse)
· 3 = no implementado en este bloque (D-B1-09). Marcadores ASCII [OK]/[AVISO]/[FALLO]/[INFO]
(cp1252 imprime acentos pero no símbolos ✓/✗).
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import SibilaError, config, db

EXIT_OK = 0
EXIT_FALLO = 1
EXIT_NO_IMPLEMENTADO = 3

log = logging.getLogger("sibila.cli")


def _utf8_stdio() -> None:
    """errors='replace' SIN forzar utf-8 (verificado por Hopper: forzar utf-8 sobre una
    consola cp1252 produce mojibake; replace + etiquetas ASCII es lo correcto).
    Protegido con getattr: hay entornos sin reconfigure (trampa T8)."""
    for flujo in (sys.stdout, sys.stderr):
        rec = getattr(flujo, "reconfigure", None)
        if rec is not None:
            rec(errors="replace")


def _linea(estado: str, mensaje: str) -> None:
    print(f"[{estado}] {mensaje}")


def _configurar_logging() -> None:
    """Handlers SOLO aquí (nunca a nivel de módulo, trampa de logging). Solo fichero:
    la consola ya es el canal de usuario vía print. Fallo de permisos degrada sin romper.
    C2 (Bloque 3): RotatingFileHandler 1 MB × 3 (Hermes corre a diario durante meses:
    sin rotación el log crecería sin límite) y sello en UTC (formatter.converter =
    time.gmtime — requisito §7: el día de datos es UTC, los logs también)."""
    raiz_log = logging.getLogger("sibila")
    if raiz_log.handlers:  # main() puede llamarse varias veces desde tests
        return
    try:
        logdir = Path(__file__).resolve().parent.parent / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(logdir / "sibila.log", maxBytes=1_000_000,
                                 backupCount=3, encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        fmt.converter = time.gmtime  # UTC en los sellos (C2)
        fh.setFormatter(fmt)
        raiz_log.addHandler(fh)
        raiz_log.setLevel(logging.DEBUG)
    except OSError as e:  # sin log a fichero: el programa sigue, consta en stderr
        print(f"[AVISO] no se pudo abrir logs/sibila.log: {e}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sibila",
        description="Núcleo del programa de lingüística predictiva (Fase 1, bloque 1).",
        epilog="ejemplos: python -m sibila init · python -m sibila check · python -m sibila doctor · "
               "exit codes: 0 OK, 1 fallo, 2 uso incorrecto, 3 no implementado")
    sub = p.add_subparsers(dest="comando", required=True)
    si = sub.add_parser("init", help="crea la base de datos y la estructura de carpetas (idempotente)")
    si.set_defaults(func=_cmd_init)
    sc = sub.add_parser("check", help="verde/rojo: DB íntegra, schema correcto, git y ots (anclaje)")
    sc.set_defaults(func=_cmd_check)
    sg = sub.add_parser("ingesta", help="una pasada de ingesta por las fuentes habilitadas (fixture o en vivo)")
    sg.add_argument("--fuente", action="append", metavar="NOMBRE",
                    help="solo esta fuente (repetible); por defecto todas las habilitadas")
    sg.add_argument("--fuentes", metavar="RUTA",
                    default=str(Path(__file__).resolve().parent.parent / "fuentes.toml"),
                    help="fuentes.toml a usar")
    sg.add_argument("--fixture", metavar="RUTA",
                    help="parsea un fichero local como una sola fuente (requiere --fuente)")
    sg.add_argument("--en-vivo", action="store_true", help="fuerza descarga aunque haya fixture")
    sg.add_argument("--sin-db", action="store_true",
                    help="solo parsea y muestra: no persiste ni mueve cursores")
    sg.add_argument("--limite", type=int, metavar="N", help="máximo de documentos por fuente")
    sg.set_defaults(func=_cmd_ingesta)
    sp = sub.add_parser("procesa", help="procesa los documentos pendientes (limpieza, "
                        "idioma, dedup, calidad, bots, emoción, n-gramas)")
    sp.add_argument("--lote", type=int, metavar="N", default=200,
                    help="documentos por lote/transacción (defecto 200)")
    sp.add_argument("--limite", type=int, metavar="N",
                    help="máximo de documentos (depuración; los demás siguen pendientes)")
    sp.add_argument("--dia", metavar="YYYY-MM-DD", help="restringe la selección a un día")
    sp.add_argument("--todo", action="store_true",
                    help="re-procesa todo el rango, no solo los pendientes")
    sp.set_defaults(func=_cmd_procesa)
    sd = sub.add_parser("detecta", help="detección temporal: z_r, CUSUM y Mann-Kendall "
                        "sobre las series diarias (escribe term_stats.z_r y signals)")
    sd.add_argument("--dia", metavar="YYYY-MM-DD", help="solo ese día")
    sd.add_argument("--desde", metavar="YYYY-MM-DD", help="primer día del rango (inclusivo)")
    sd.add_argument("--hasta", metavar="YYYY-MM-DD", help="último día del rango "
                    "(defecto: ayer UTC; requiere --desde)")
    sd.add_argument("--todo", action="store_true",
                    help="desde el primer día con stats hasta ayer (o --hasta)")
    sd.set_defaults(func=_cmd_detecta)
    reg = sub.add_parser("registro", help="registro sellado de predicciones "
                         "(cadena JSONL + tabla predictions)")
    rsub = reg.add_subparsers(dest="accion", required=True)
    rs = rsub.add_parser("sellar", help="sella las señales del día/rango como predicciones")
    rs.add_argument("--dia", metavar="YYYY-MM-DD", help="solo ese día")
    rs.add_argument("--desde", metavar="YYYY-MM-DD", help="primer día del rango (inclusivo)")
    rs.add_argument("--hasta", metavar="YYYY-MM-DD",
                    help="último día del rango (defecto: ayer UTC; requiere --desde)")
    rs.set_defaults(func=_cmd_registro_sellar)
    rv = rsub.add_parser("verificar", help="verifica la cadena y el cruce con la tabla")
    rv.set_defaults(func=_cmd_registro_verificar)
    ra = rsub.add_parser("anclar", help="ancla el registro en git (+ ots si existe)")
    ra.set_defaults(func=_cmd_registro_anclar)
    rl = rsub.add_parser("listar", help="lista la tabla predictions (sin escritura)")
    rl.add_argument("--pendientes", action="store_true", help="solo las pendientes")
    rl.set_defaults(func=_cmd_registro_listar)
    si = sub.add_parser("informe", help="informe del período (defecto: semana ISO "
                        "terminando ayer); lectura siempre en modo solo-lectura")
    si.add_argument("--semana", metavar="AAAA-Www", help="semana ISO (p. ej. 2026-W34)")
    si.add_argument("--dia", metavar="YYYY-MM-DD", help="solo ese día")
    si.add_argument("--desde", metavar="YYYY-MM-DD", help="primer día del rango")
    si.add_argument("--hasta", metavar="YYYY-MM-DD", help="último día (requiere --desde)")
    si.add_argument("--salida", metavar="RUTA", help="fichero destino (defecto: stdout)")
    si.add_argument("--formato", metavar="FORMATO",
                    help="md (defecto), json o csv (vectores congelados §6.1)")
    si.add_argument("--actualizar-gdelt", action="store_true",
                    help="subacción ESCRITORA aparte: descarga referencia GDELT")
    si.set_defaults(func=_cmd_informe)
    sa = sub.add_parser("alerta", help="alertas por red (Telegram/SMTP) y digest semanal")
    asub = sa.add_subparsers(dest="accion", required=True)
    ae = asub.add_parser("enviar", help="envía las alertas del período (defecto: ayer)")
    ae.add_argument("--dia", metavar="YYYY-MM-DD", help="solo ese día")
    ae.add_argument("--desde", metavar="YYYY-MM-DD", help="primer día del rango")
    ae.add_argument("--hasta", metavar="YYYY-MM-DD", help="último día (requiere --desde)")
    ae.set_defaults(func=_cmd_alerta_enviar)
    ap = asub.add_parser("probar", help="envía un mensaje de prueba (TP-N7)")
    ap.set_defaults(func=_cmd_alerta_probar)
    ad = asub.add_parser("digest", help="digest semanal de alertas (canal 'digest')")
    ad.add_argument("--semana", metavar="AAAA-Www", help="semana ISO (defecto: la de ayer)")
    ad.set_defaults(func=_cmd_alerta_digest)
    sc = sub.add_parser("corre", help="pipeline diario completo (ingesta→procesa→"
                        "detecta→sellar→alerta) para un día o rango")
    sc.add_argument("--dia", metavar="YYYY-MM-DD", help="solo ese día")
    sc.add_argument("--desde", metavar="YYYY-MM-DD", help="primer día del rango")
    sc.add_argument("--hasta", metavar="YYYY-MM-DD", help="último día (requiere --desde)")
    sc.add_argument("--fuente", metavar="NOMBRE", help="fuente de los fixtures RSS")
    sc.add_argument("--fixture", metavar="FEED", help="RSS de un solo día (exige --dia y --fuente)")
    sc.add_argument("--fixture-dir", metavar="DIR",
                    help="directorio con {dia}.xml por día (exige --desde y --fuente)")
    sc.add_argument("--digest", action="store_true",
                    help="además, digest de la semana ISO que contiene el día")
    sc.add_argument("--con-informe", action="store_true",
                    help="además, informe del período (stdout)")
    sc.set_defaults(func=_cmd_corre)
    sdoc = sub.add_parser("doctor", help="comprobación post-instalación: deps, "
                          "recursos con SHA-256, data_dir, git/ots y secretos")
    sdoc.set_defaults(func=_cmd_doctor)
    spq = sub.add_parser("paquete", help="manifiesto SHA-256 del paquete "
                         "(generar al empaquetar; verificar en destino)")
    psq = spq.add_subparsers(dest="accion", required=True)
    spg = psq.add_parser("generar", help="regenera MANIFIESTO.sha256.json "
                         "(solo al construir el paquete)")
    spg.set_defaults(func=_cmd_paquete_generar)
    spv = psq.add_parser("verificar", help="verifica integridad (exit 0/1)")
    spv.set_defaults(func=_cmd_paquete_verificar)
    return p


def _cmd_init(args) -> int:
    cfg = config.load_config()
    _aplicar_nivel(cfg)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "registro").mkdir(parents=True, exist_ok=True)  # D-B6-02
    db.init_db(cfg.db_path)
    con = db.connect(cfg.db_path)
    try:
        problemas = db.verify_schema(con)
    finally:
        con.close()
    if problemas:
        for p in problemas:
            _linea("FALLO", p)
        return EXIT_FALLO
    _linea("OK", f"base de datos lista en {cfg.db_path}")
    _linea("INFO", "schema v1, 12 tablas")
    _linea("INFO", f"registro sellado en {cfg.data_dir / 'registro'}")
    for a in cfg.avisos:
        _linea("INFO", a)
    # Mensaje fiel al estado real (D-077): el instalador puede haber creado
    # ya config.local.toml antes de init; afirmar siempre "no se crea" era
    # contradictorio. La raíz es la misma que usa load_config por defecto.
    p_local = Path(__file__).resolve().parent.parent / "config.local.toml"
    if p_local.exists():
        _linea("OK", "secretos: config.local.toml ya existe (creado en la "
                     "instalación; no se toca)")
    else:
        _linea("INFO", "secretos: config.local.toml no se crea (los decide el "
                       "operador; plantilla en config.local.toml.example)")
    return EXIT_OK


def _aplicar_nivel(cfg) -> None:
    """log_level se valida Y se aplica (rev. Hamilton: clave muerta no)."""
    logging.getLogger("sibila").setLevel(getattr(logging, cfg.log_level, logging.INFO))


def _cmd_check(args) -> int:
    """Todos los chequeos corren aunque alguno falle (informe completo; rev. B1: ningún
    chequeo puede amputar el informe); NO repara nada (reparar es de init).
    Avisos NUNCA penalizan (TP-N1 admite anclaje 'pendiente')."""
    fallos = avisos = ok = 0

    def marca(estado: str, msg: str) -> None:
        nonlocal fallos, avisos, ok
        _linea(estado, msg)
        if estado == "FALLO":
            fallos += 1
        elif estado == "AVISO":
            avisos += 1
        elif estado == "OK":
            ok += 1

    # 1 · Intérprete (rev. M4: 3.13+ es AVISO "no probado", no FALLO)
    v = sys.version_info
    if (v.major, v.minor) == (3, 12):
        marca("OK", f"intérprete Python {v.major}.{v.minor}.{v.micro}")
    elif v.major == 3 and v.minor >= 11:
        marca("AVISO", f"Python {v.major}.{v.minor}: distinto del objetivo 3.12 (spec §3); no probado")
    else:
        marca("FALLO", f"Python {v.major}.{v.minor}: se necesita 3.12 (mínimo 3.11 por tomllib)")

    # 2 · Recursos del paquete
    try:
        db._schema_sql()
        marca("OK", "recursos del paquete accesibles (schema.sql)")
    except Exception as e:
        marca("FALLO", f"schema.sql inaccesible: {e} (repo incompleto)")

    # 3 · Config
    cfg = None
    try:
        cfg = config.load_config()
        _aplicar_nivel(cfg)
        marca("OK", "configuración cargada")
        for a in cfg.avisos:
            _linea("INFO", a)
    except (config.ConfigError, OSError) as e:  # rev. M7: config.toml como directorio o ilegible
        marca("FALLO", f"configuración: {e}")

    # 4 · Rutas de datos escribibles (sonda con pid: dos check concurrentes no colisionan — rev. M1)
    if cfg is not None:
        if not cfg.data_dir.exists():
            marca("FALLO", f"no existe {cfg.data_dir}; ejecuta 'sibila init'")
        else:
            try:
                sonda = cfg.data_dir / f".sonda_escritura_{os.getpid()}"
                sonda.write_text("ok", encoding="utf-8")
                sonda.unlink()
                marca("OK", f"directorio de datos escribible ({cfg.data_dir})")
                libre = shutil.disk_usage(cfg.data_dir).free
                if libre < 1_000_000_000:
                    marca("AVISO", f"espacio libre bajo: {libre // 1_000_000} MB")
            except OSError as e:
                marca("FALLO", f"directorio de datos no escribible: {e}")

    # 5-9 · Base de datos
    con = None
    if cfg is not None:
        if not cfg.db_path.exists():
            marca("FALLO", f"no existe {cfg.db_path}; ejecuta 'sibila init'")
            _linea("INFO", "integridad, pragmas y schema no evaluables sin base de datos")
        else:
            try:
                con = db.connect(cfg.db_path)  # conexión NUEVA: los pragmas se verifican de verdad
                marca("OK", f"base de datos abre ({cfg.db_path})")
            except sqlite3.Error as e:
                marca("FALLO", f"la base no abre: {e}")
    if con is not None:
        try:
            # rev. B1′: integrity_check puede LANZAR (página intermedia corrompida), no solo
            # devolver != 'ok' — toda la sección DB protegida para que el informe llegue al resumen
            marca("OK" if db.integrity_ok(con) else "FALLO", "integridad SQLite (integrity_check)")
            for pragma, esperado in (("journal_mode", "wal"), ("foreign_keys", 1),
                                     ("busy_timeout", db.BUSY_TIMEOUT_MS)):
                real = con.execute(f"PRAGMA {pragma}").fetchone()[0]
                if str(real).lower() == str(esperado):
                    marca("OK", f"pragma {pragma}={real}")
                else:
                    marca("FALLO", f"pragma {pragma}={real}, esperado {esperado}")
            problemas = db.verify_schema(con)
            if not problemas:
                marca("OK", "schema v1 conforme (12 tablas)")
            else:
                for p in problemas:
                    marca("FALLO", f"schema: {p}")
            try:  # rev. B1: si la tabla falta, el informe SIGUE (el FALLO de schema ya lo dice)
                n_eco = con.execute("SELECT COUNT(*) FROM echo_flags").fetchone()[0]
                if n_eco == 0:
                    marca("OK", "echo_flags: 0 filas (vacía en Fase 1, contrato congelado)")
                else:
                    marca("FALLO", f"echo_flags tiene {n_eco} filas: en Fase 1 solo escribe el módulo anti-eco (Fase 2)")
            except sqlite3.Error as e:
                marca("FALLO", f"echo_flags no evaluable: {e}")
        except sqlite3.Error as e:
            marca("FALLO", f"base de datos no evaluable: {e}")
        finally:
            con.close()

    # 10 · git (anclaje del registro; AVISO, nunca fallo — TP-N1)
    git = shutil.which("git")
    if git:
        marca("OK", f"git: {git}")
    else:
        marca("AVISO", "git no encontrado: el anclaje del registro quedará pendiente (TP-N5)")

    # 11 · ots (OpenTimestamps; AVISO, nunca fallo)
    if shutil.which("ots"):
        marca("OK", "opentimestamps disponible")
    else:
        marca("AVISO", "opentimestamps no instalado: anclaje 'pendiente' (requirements-extra, bloque registro)")

    # 12 · Log de prueba REAL (rev. Hamilton: logging traga errores del handler → exigir que el fichero crezca)
    try:
        logfile = Path(__file__).resolve().parent.parent / "logs" / "sibila.log"
        antes = logfile.stat().st_size if logfile.exists() else 0
        log.info("sonda de log del comando check")
        for h in logging.getLogger("sibila").handlers:
            h.flush()
        if logfile.exists() and logfile.stat().st_size > antes:
            marca("OK", "log de prueba escrito en logs/sibila.log")
        else:
            marca("FALLO", "el log no creció: handler ausente o sin permisos")
    except OSError as e:
        marca("FALLO", f"no se pudo escribir el log: {e}")

    _linea("INFO", f"resultado: {ok} correctos, {avisos} avisos, {fallos} fallos")
    if fallos:
        print(f"check: ROJO ({fallos} fallos)")
        return EXIT_FALLO
    print("check: VERDE")
    return EXIT_OK


def _cmd_ingesta(args, dormir=time.sleep) -> int:
    """Una pasada por las fuentes habilitadas. Una fuente caída NO tumba a las demás:
    se marca [FALLO] y el resumen llega al final (aislamiento por fuente).
    C1 (Bloque 3): descanso de 2 s ENTRE fuentes de red (n-1 descansos), cortesía con
    los servidores en producción; 0 s con fixtures y en --sin-db (D-032 desv. 10).
    `dormir` es inyectable para tests (cuenta exacta de descansos)."""
    from . import ingesta as ing  # imports perezosos: init/check no cargan conectores
    from .conectores import cargar_fuentes, conectores_habilitados

    # Validaciones de uso (exit 2 = uso incorrecto, convención argparse)
    if args.en_vivo and args.fixture:
        print("[FALLO] --en-vivo y --fixture son incompatibles", file=sys.stderr)
        return 2
    if args.limite is not None and args.limite < 1:
        print("[FALLO] --limite debe ser >= 1", file=sys.stderr)
        return 2
    if args.fixture and not args.fuente:
        print("[FALLO] --fixture requiere --fuente NOMBRE", file=sys.stderr)
        return 2
    if args.fixture and len(args.fuente) > 1:
        print("[FALLO] --fixture solo admite UNA fuente (rev. Dijkstra M3/Hamilton M10: "
              "asignarlo a varias contamina las fuentes)", file=sys.stderr)
        return 2

    cfg = config.load_config()
    _aplicar_nivel(cfg)
    try:
        fuentes = cargar_fuentes(args.fuentes)
        habilitados = conectores_habilitados(fuentes)
    except (OSError, ValueError) as e:
        print(f"[FALLO] fuentes: {e}", file=sys.stderr)
        return EXIT_FALLO

    if args.fuente:
        deseadas = set(args.fuente)
        habilitados = [c for c in habilitados if c.nombre in deseadas]
        if not habilitados:
            print(f"[FALLO] ninguna fuente habilitada coincide con {sorted(deseadas)}",
                  file=sys.stderr)
            return EXIT_FALLO
    if args.fixture:
        habilitados[0].cfg["fixture"] = str(Path(args.fixture).resolve())
    if args.en_vivo:
        for c in habilitados:
            c.cfg.pop("fixture", None)

    con = None
    if not args.sin_db:
        if not cfg.db_path.exists():
            print(f"[FALLO] no existe {cfg.db_path}; ejecuta 'sibila init'", file=sys.stderr)
            return EXIT_FALLO
        con = db.connect(cfg.db_path)
        ing.asegurar_fuentes(con)
        if not cfg.secretos.get("hmac_key"):  # aviso UNA vez por ejecución (plan §5.3)
            _linea("AVISO", "sin hmac_key: author_hash quedará NULL "
                            "(nunca identidad en claro, spec §6.8)")
        if args.limite:  # rev. Hamilton N1 r2: el cursor no se mueve con límite
            _linea("AVISO", f"--limite {args.limite} activo: el cursor NO se mueve "
                            "(modo depuración)")

    algun_fallo = False
    tot = {"nuevos": 0, "dups": 0, "errores": 0}
    anterior_fue_red = False
    try:
        for conector in habilitados:
            nombre = conector.nombre
            # C1: descanso solo ENTRE dos fuentes de RED consecutivas y solo con DB
            # (rev. Hamilton M3 r3: red→fixture no molesta a ningún servidor)
            actual_es_red = not conector.cfg.get("fixture")
            if anterior_fue_red and actual_es_red and not args.sin_db:
                dormir(2.0)
            anterior_fue_red = actual_es_red
            try:
                if args.sin_db:
                    docs, _cur = conector.fetch(conector.cfg, None)
                    if args.limite:
                        docs = docs[: args.limite]
                    for d in docs:
                        fecha = d.published_at.isoformat() if d.published_at else "(sin fecha)"
                        print(f"  - [{d.fuente}] {d.url or '(sin url)'} · {fecha} · {len(d.body)} caracteres")
                    if docs:
                        _linea("OK", f"{nombre}: {len(docs)} documentos parseados (modo --sin-db, nada persistido)")
                    else:  # 0 documentos NUNCA es [OK] silencioso (plan T-C4, rev. M12)
                        _linea("AVISO", f"{nombre}: 0 documentos (¿feed roto o vacío?)")
                    continue
                cursor = ing.leer_cursor(con, nombre)
                res = ing.ingestar(cfg, conector, cursor, con, limite=args.limite)
                if res["recibidos"] == 0:
                    if res["cursor"] == cursor:  # cursor sin cambios (304 o equivalente)
                        _linea("OK", f"{nombre}: sin novedades (cursor sin cambios)")
                    else:  # 200 con 0 entradas: ¿feed roto o vacío? (plan T-C4)
                        _linea("AVISO", f"{nombre}: 0 documentos (¿feed roto o vacío?)")
                else:
                    if res["errores"]:
                        _linea("AVISO", f"{nombre}: {res['errores']} documentos con error (saltados)")
                    _linea("OK", f"{nombre}: {res['nuevos']} nuevos · {res['dup_url']} dup url · "
                                 f"{res['dup_cont']} dup contenido · {res['errores']} errores")
                tot["nuevos"] += res["nuevos"]
                tot["dups"] += res["dup_url"] + res["dup_cont"]
                tot["errores"] += res["errores"]
            except Exception as e:
                algun_fallo = True
                log.exception("ingesta %s", nombre)
                _linea("FALLO", f"{nombre}: {e}")
    finally:
        if con is not None:
            con.close()
    if args.sin_db:
        _linea("INFO", "modo sin-db: nada se escribió")
    else:  # resumen total (C-B2-10)
        _linea("INFO", f"ingesta: {tot['nuevos']} nuevos, {tot['dups']} duplicados, "
                       f"{tot['errores']} errores")
    return EXIT_FALLO if algun_fallo else EXIT_OK


def _cmd_procesa(args) -> int:
    """Procesa los documentos pendientes en lotes transaccionales (Bloque 4)."""
    from datetime import datetime  # validación de --dia; la hora la estampa db.now_iso()
    from . import procesa as proc  # import perezoso: init/check no cargan el pipeline

    if args.lote < 1:
        print("[FALLO] --lote debe ser >= 1", file=sys.stderr)
        return 2
    if args.limite is not None and args.limite < 1:
        print("[FALLO] --limite debe ser >= 1", file=sys.stderr)
        return 2
    if args.dia is not None:
        try:
            datetime.strptime(args.dia, "%Y-%m-%d")
        except ValueError:
            print(f"[FALLO] --dia inválido: {args.dia!r} (formato YYYY-MM-DD)",
                  file=sys.stderr)
            return 2
    cfg = config.load_config()
    _aplicar_nivel(cfg)
    if not cfg.db_path.exists():
        print(f"[FALLO] no existe {cfg.db_path}; ejecuta 'sibila init'", file=sys.stderr)
        return EXIT_FALLO
    con = db.connect(cfg.db_path)
    try:
        res = proc.ejecutar(cfg, con, lote=args.lote, dia=args.dia,
                            todo=args.todo, limite=args.limite)
    finally:
        con.close()
    for a in res["avisos"]:
        _linea("AVISO", a)
    for info in res["lotes"]:
        _linea("INFO", info)
    c = res["contadores"]
    if res["pendientes"] == 0:
        _linea("OK", "procesa: sin documentos pendientes")
        return EXIT_OK
    excluidos = c["excluidos_fecha"] + c["excluidos_dup"] + c["sin_idioma"]
    _linea("INFO", f"procesa: {c['procesados']} procesados, {excluidos} excluidos "
                   f"(fecha/dup/idioma), {c['near_dup']} near-dup, "
                   f"{c['republicados']} republicados, {c['errores']} errores, "
                   f"{c['dias_recalculados']} días recalculados")
    _linea("OK" if c["errores"] == 0 else "AVISO",
           f"procesa: ejecución terminada ({c['procesados']} procesados, "
           f"{c['errores']} errores)")
    return EXIT_OK


def _cmd_detecta(args) -> int:
    """Detección temporal sobre el rango pedido (Bloque 5). Validaciones de uso
    ANTES de abrir la BD (trampa 12); exit codes congelados 0/1/2."""
    from datetime import date  # validación de fechas; la hora la estampa db.now_iso()
    from . import detecta as det   # import perezoso

    def _fecha_valida(txt):
        # date.fromisoformat (NO strptime: acepta '2026-8-3' y luego detecta
        # explotaría con ValueError desnudo — rev. Dijkstra M1)
        try:
            date.fromisoformat(txt)
            return True
        except (ValueError, TypeError):
            return False

    for nombre, valor in (("--dia", args.dia), ("--desde", args.desde),
                          ("--hasta", args.hasta)):
        if valor is not None and not _fecha_valida(valor):
            print(f"[FALLO] {nombre} inválido: {valor!r} (formato YYYY-MM-DD)",
                  file=sys.stderr)
            return 2
    if args.dia and (args.desde or args.hasta or args.todo):
        print("[FALLO] --dia es incompatible con --desde/--hasta/--todo",
              file=sys.stderr)
        return 2
    if args.hasta and not args.desde:
        print("[FALLO] --hasta requiere --desde", file=sys.stderr)
        return 2
    if args.todo and (args.desde or args.hasta):
        print("[FALLO] --todo es incompatible con --desde/--hasta", file=sys.stderr)
        return 2
    if args.desde and args.hasta and args.desde > args.hasta:
        print("[FALLO] --desde no puede ser posterior a --hasta", file=sys.stderr)
        return 2
    cfg = config.load_config()
    _aplicar_nivel(cfg)
    if not cfg.db_path.exists():
        print(f"[FALLO] no existe {cfg.db_path}; ejecuta 'sibila init'", file=sys.stderr)
        return EXIT_FALLO
    con = db.connect(cfg.db_path)
    try:
        res = det.ejecutar(cfg, con, desde=args.desde, hasta=args.hasta,
                           dia=args.dia, todo=args.todo)
    finally:
        con.close()
    if res["sin_datos"]:
        _linea("OK", "detecta: sin datos suficientes (primer día)")
        return EXIT_OK
    for i in res["infos"]:
        _linea("INFO", i)
    for a in res["avisos"]:
        _linea("AVISO", a)
    n_eval = sum(1 for _d, c in res["dias"] if c["dias_evaluados"])
    _linea("INFO", f"detecta: {n_eval} días evaluados, {res['senales']} señales "
                   f"nuevas/actualizadas ({res['inmaduras']} inmaduras)")
    _linea("OK", "detecta: ejecución terminada")
    return EXIT_OK


def _cmd_registro_sellar(args) -> int:
    """Sella señales como predicciones. La CLI NO pre-valida formato de ventana
    ni línea (M4 Turing): única fuente de verdad = la capa pura."""
    from datetime import date  # date.fromisoformat, patrón consolidado
    from . import sella

    def _fecha_ok(txt):
        try:
            date.fromisoformat(txt)
            return True
        except (ValueError, TypeError):
            return False
    for nombre, valor in (("--dia", args.dia), ("--desde", args.desde),
                          ("--hasta", args.hasta)):
        if valor is not None and not _fecha_ok(valor):
            print(f"[FALLO] {nombre} inválido: {valor!r} (formato YYYY-MM-DD)",
                  file=sys.stderr)
            return 2
    if args.dia and (args.desde or args.hasta):
        print("[FALLO] --dia es incompatible con --desde/--hasta", file=sys.stderr)
        return 2
    if args.hasta and not args.desde:
        print("[FALLO] --hasta requiere --desde", file=sys.stderr)
        return 2
    if args.desde and args.hasta and args.desde > args.hasta:
        print("[FALLO] --desde no puede ser posterior a --hasta", file=sys.stderr)
        return 2
    cfg = config.load_config()
    _aplicar_nivel(cfg)
    if not cfg.db_path.exists():
        print(f"[FALLO] no existe {cfg.db_path}; ejecuta 'sibila init'", file=sys.stderr)
        return EXIT_FALLO
    con = db.connect(cfg.db_path)
    try:
        res = sella.ejecutar(cfg, con, desde=args.desde, hasta=args.hasta,
                             dia=args.dia)
    finally:
        con.close()
    for a in res["avisos"]:
        _linea("AVISO", a)
    c = res["contadores"]
    if c["selladas"] == 0 and c["omitidas"] == 0 and c["reconciliadas"] == 0:
        _linea("OK", "registro: sin señales que sellar")
    else:
        _linea("OK", f"registro: {c['selladas']} predicciones selladas "
                     f"({c['inmaduras']} inmaduras), {c['omitidas']} omitidas "
                     f"(ya pendientes), {c['reconciliadas']} reconciliadas")
    return EXIT_OK


def _cmd_registro_verificar(args) -> int:
    """Verifica cadena + cruce fichero↔tabla + anclaje. Exit EXACTAMENTE 0/1
    (contrato §4.4)."""
    from . import sella
    cfg = config.load_config()
    _aplicar_nivel(cfg)
    if not cfg.db_path.exists():
        print(f"[FALLO] no existe {cfg.db_path}; ejecuta 'sibila init'", file=sys.stderr)
        return EXIT_FALLO
    con = db.connect(cfg.db_path)
    try:
        res = sella.verificar(cfg, con)
    finally:
        con.close()
    if res["cola_coja"]:
        _linea("AVISO", "registro: cola incompleta al final del fichero "
                        "(crash previo); la cadena completa sigue verificada")
    if res["ok"]:
        _linea("OK", "cadena: íntegra (génesis, hashes, encadenamiento, orden)")
        _linea("OK", "cruce fichero↔tabla: idénticos")
    else:
        for r in res["roturas"]:
            _linea("FALLO", r)
    corto = (res["ultimo_hash"] or "")[:8] or "—"
    _linea("INFO", f"registro: {res['n_lineas']} líneas, último hash {corto}, "
                   f"anclaje {res['anclaje']}")
    if res["ok"]:
        _linea("OK", "registro: ÍNTEGRO")
        return EXIT_OK
    _linea("FALLO", f"registro: ROTO ({len(res['roturas'])} roturas)")
    return EXIT_FALLO


def _cmd_registro_anclar(args) -> int:
    """Ancla el JSONL en el git interno de registro/ (+ ots si existe)."""
    from . import anclaje
    cfg = config.load_config()
    _aplicar_nivel(cfg)
    if not cfg.db_path.exists():
        print(f"[FALLO] no existe {cfg.db_path}; ejecuta 'sibila init'", file=sys.stderr)
        return EXIT_FALLO
    con = db.connect(cfg.db_path)
    try:
        res = anclaje.anclar(cfg, con)
    finally:
        con.close()
    if res["aviso"] and res["aviso"] != "anclaje: sin cambios":
        _linea("AVISO", res["aviso"])
    elif res["aviso"]:
        _linea("OK", f"registro {res['aviso']}")
    if res["anclado"] and res["commit"]:
        _linea("OK", f"anclaje: {res['n_lineas']} líneas en commit "
                     f"{res['commit'][:8]}")
    return EXIT_OK


def _cmd_registro_listar(args) -> int:
    """Lista la TABLA predictions (E1: nunca el JSONL). Sin escritura."""
    cfg = config.load_config()
    _aplicar_nivel(cfg)
    if not cfg.db_path.exists():
        print(f"[FALLO] no existe {cfg.db_path}; ejecuta 'sibila init'", file=sys.stderr)
        return EXIT_FALLO
    con = db.connect(cfg.db_path)
    try:
        sql = ("SELECT id, tema, metrica, umbral, ventana, estado, madura,"
               " created_at FROM predictions")
        if args.pendientes:
            sql += " WHERE estado = 'pendiente'"
        filas = con.execute(sql + " ORDER BY id ASC").fetchall()
    finally:
        con.close()
    if not filas:
        _linea("OK", "registro: sin predicciones")
        return EXIT_OK
    for f in filas:
        mad = " inmadura" if not f["madura"] else ""
        _linea("INFO", f"#{f['id']} {f['tema']} · {f['metrica']} ≥ {f['umbral']} · "
                       f"{f['ventana']} · {f['estado']}{mad} · {f['created_at']}")
    _linea("OK", f"registro: {len(filas)} predicciones")
    return EXIT_OK


def _hoy_utc():
    """Fecha de hoy EN UTC (MED-1, resuelta en D-077): los rangos por defecto
    del CLI deben seguir el mismo reloj que el sellado (db.now_iso, UTC).
    Antes usaban date.today() local: cerca de la medianoche local, si la
    fecha local ≠ fecha UTC, «ayer» no coincidía con el día sellado.
    Derivada de now_iso para que los tests puedan fijar el instante."""
    from datetime import date
    return date.fromisoformat(db.now_iso()[:10])


def _validar_rango(dia, desde, hasta):
    """Validaciones de rango ANTES de abrir la BD (trampa 12); exit 2."""
    from datetime import date, timedelta

    def _fecha_ok(txt):
        try:
            date.fromisoformat(txt)
            return True
        except (ValueError, TypeError):
            return False
    for nombre, valor in (("--dia", dia), ("--desde", desde), ("--hasta", hasta)):
        if valor is not None and not _fecha_ok(valor):
            print(f"[FALLO] {nombre} inválido: {valor!r} (formato YYYY-MM-DD)",
                  file=sys.stderr)
            return None
    if dia and (desde or hasta):
        print("[FALLO] --dia es incompatible con --desde/--hasta", file=sys.stderr)
        return None
    if hasta and not desde:
        print("[FALLO] --hasta requiere --desde", file=sys.stderr)
        return None
    if desde and hasta and desde > hasta:
        print("[FALLO] --desde no puede ser posterior a --hasta", file=sys.stderr)
        return None
    ayer = (_hoy_utc() - timedelta(days=1)).isoformat()
    if dia:
        return dia, dia
    if desde:
        return desde, hasta or ayer
    return ayer, ayer


def _semana_a_rango(txt):
    """'2026-W34' → (lunes, domingo) ISO; semana inexistente → None (exit 2)."""
    import re
    from datetime import date, timedelta
    if not re.fullmatch(r"\d{4}-W\d{2}", txt or ""):
        return None
    try:
        lunes = date.fromisocalendar(int(txt[:4]), int(txt[6:]), 1)
    except ValueError:
        return None
    return lunes.isoformat(), (lunes + timedelta(days=6)).isoformat()


def _cfg_y_bd():
    cfg = config.load_config()
    _aplicar_nivel(cfg)
    if not cfg.db_path.exists():
        print(f"[FALLO] no existe {cfg.db_path}; ejecuta 'sibila init'", file=sys.stderr)
        return cfg, None
    return cfg, cfg.db_path


def _stdout_seguro():
    """Consola cp1252 degradada segura (trampa 17): byte-exacto solo se exige
    al FICHERO; la consola reemplaza, nunca UnicodeEncodeError."""
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def _cmd_informe(args) -> int:
    """Informe del período. SIEMPRE mode=ro (excepto la subacción escritora
    --actualizar-gdelt, que es otra invocación y NUNCA se mezcla, M3)."""
    from . import gdelt, informe_datos as informe

    cfg = config.load_config()
    _aplicar_nivel(cfg)
    # Validación de flags ANTES de abrir la BD (rev. Dijkstra M8): un formato
    # no soportado es exit 2 aunque la BD no exista.
    formato = args.formato
    if args.salida and formato is None:               # inferir por extensión
        ext = args.salida.rsplit(".", 1)[-1].lower() if "." in args.salida else ""
        if ext not in ("md", "json", "csv"):
            print(f"[FALLO] --salida con extensión ambigua: {args.salida!r}; "
                  "indica --formato", file=sys.stderr)
            return 2
        formato = ext
    formato = formato or "md"
    if formato not in ("md", "json", "csv"):
        print(f"[FALLO] formato {formato!r} no soportado; formatos: md, json, csv",
              file=sys.stderr)
        return 2
    if not cfg.db_path.exists():
        print(f"[FALLO] no existe {cfg.db_path}; ejecuta 'sibila init'", file=sys.stderr)
        return EXIT_FALLO
    if args.actualizar_gdelt:                     # subacción escritora aparte
        con = db.connect(cfg.db_path)
        try:
            desde, hasta = informe.semana_iso(
                _hoy_utc() - __import__("datetime").timedelta(1))
            temas = gdelt.temas_de_la_semana(con, desde, hasta)
            if not temas:
                _linea("OK", "gdelt: sin temas de la semana que referenciar")
                return EXIT_OK
            res = gdelt.actualizar(cfg, con, temas=temas, dias=[desde])
        finally:
            con.close()
        for a in res["avisos"]:
            _linea("AVISO", a)
        _linea("OK", f"gdelt: {res['escritos']} referencias actualizadas, "
                     f"{res['vacios']} n/d, {res['fallos']} fallos")
        return EXIT_OK
    # Rango: --semana | --dia | --desde/--hasta | defecto = semana ISO de ayer
    from datetime import timedelta
    ayer = _hoy_utc() - timedelta(days=1)
    if args.semana:
        rango = _semana_a_rango(args.semana)
        if rango is None:
            print(f"[FALLO] --semana inválida: {args.semana!r} (formato AAAA-Www ISO)",
                  file=sys.stderr)
            return 2
        desde, hasta = rango
    elif args.dia or args.desde or args.hasta:
        rango = _validar_rango(args.dia, args.desde, args.hasta)
        if rango is None:
            return 2
        desde, hasta = rango
    else:
        desde, hasta = informe.semana_iso(ayer)      # A-B7-1: defecto SEMANA
    con = informe.conectar_ro(cfg.db_path)            # SIEMPRE ro (D-B7)
    try:
        res = informe.ejecutar(cfg, con, desde=desde, hasta=hasta, formato=formato)
    finally:
        con.close()
    if args.salida:
        informe.escribir_fichero(args.salida, res["contenido"], res["meta"])
        _linea("OK", f"informe: {res['dia']} generada (7 secciones, "
                     f"{res['n_alertas']} alertas, {res['n_predicciones']} "
                     f"predicciones activas) en {args.salida}")
    else:
        _stdout_seguro()
        contenido = res["contenido"]
        if isinstance(contenido, bytes):              # §6.1: json/csv son BYTES
            sys.stdout.buffer.write(contenido)        # nunca repr(b'...')
        else:
            print(contenido, end="" if contenido.endswith("\n") else "\n")
        _linea("OK", f"informe: {res['dia']} generada (7 secciones, "
                     f"{res['n_alertas']} alertas, {res['n_predicciones']} "
                     f"predicciones activas)")
    return EXIT_OK


def _cmd_alerta_enviar(args) -> int:
    """Envía las alertas del período (defecto: ayer UTC)."""
    from . import alerta
    rango = _validar_rango(args.dia, args.desde, args.hasta)
    if rango is None:
        return 2
    desde, hasta = rango
    cfg, ruta = _cfg_y_bd()
    if ruta is None:
        return EXIT_FALLO
    con = db.connect(cfg.db_path)
    try:
        res = alerta.ejecutar(cfg, con, desde=desde, hasta=hasta)
    finally:
        con.close()
    for a in res["avisos"]:
        _linea("AVISO", a)
    for nivel, texto in res["lineas"]:
        _linea(nivel, texto)
    c = res["contadores"]
    if res["sin_alertas"]:
        _linea("OK", "alerta: sin alertas que enviar")
        return EXIT_OK
    _linea("INFO", f"alerta: {c['enviadas']} enviadas, {c['cooldown_omitidas']} "
                   f"cooldown, {c['fallos']} fallos")
    if res["todos_caidos"] or (c["sin_credenciales"] and c["enviadas"] == 0
                               and res.get("a_enviar", 0) > 0):
        # exit 1 SOLO si había algo que enviar (rev. Dijkstra M2: si el
        # cooldown ya lo suprimió TODO, no hay nada que enviar → exit 0)
        print("[FALLO] alerta: todos los canales habilitados fallaron",
              file=sys.stderr)
        return EXIT_FALLO
    _linea("OK", "alerta: envío terminado")
    return EXIT_OK


def _cmd_alerta_probar(args) -> int:
    """TP-N7: mensaje de prueba; el intento queda registrado aunque falle."""
    from . import alerta
    cfg, ruta = _cfg_y_bd()
    if ruta is None:
        return EXIT_FALLO
    con = db.connect(cfg.db_path)
    try:
        res = alerta.probar(cfg, con)
    finally:
        con.close()
    for a in res["avisos"]:
        _linea("AVISO", a)
    if res["ok"]:
        _linea("OK", f"alerta: mensaje de prueba recibido por {res['canal']}")
        return EXIT_OK
    print(f"[FALLO] alerta probar: {res['error']}", file=sys.stderr)
    return EXIT_FALLO


def _cmd_alerta_digest(args) -> int:
    """Digest semanal (canal 'digest'; anti-duplicación 168 h)."""
    from . import alerta, informe_datos as informe
    from datetime import timedelta
    cfg, ruta = _cfg_y_bd()
    if ruta is None:
        return EXIT_FALLO
    if args.semana:
        rango = _semana_a_rango(args.semana)
        if rango is None:
            print(f"[FALLO] --semana inválida: {args.semana!r} (formato AAAA-Www ISO)",
                  file=sys.stderr)
            return 2
        desde, hasta = rango
    else:
        desde, hasta = informe.semana_iso(_hoy_utc() - timedelta(days=1))
    con = db.connect(cfg.db_path)
    try:
        res = alerta.digest(cfg, con, desde=desde, hasta=hasta)
    finally:
        con.close()
    if res["enviado"]:
        _linea("OK", f"alerta digest: {res['lineas']} líneas enviadas y registradas")
        return EXIT_OK
    _linea("AVISO", f"alerta digest: no enviado ({res['motivo']})")
    return EXIT_OK


def _ahora_defecto_cli():
    """ÚNICA función del CLI que lee el reloj real (guardián AST C-T1):
    `corre` sin flags temporales analiza ayer UTC con observación ahora
    (semántica de producción intacta, C-T1-2)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _raiz_paquete() -> Path:
    """Raíz del paquete: el directorio que CONTIENE a sibila/ (cwd típico al
    verificar en destino; estable por la posición del propio módulo)."""
    return Path(__file__).resolve().parent.parent


def _cmd_paquete_generar(args) -> int:
    """Regenera MANIFIESTO.sha256.json (paso explícito del empaquetado,
    D-048.1; no lo necesita el usuario final)."""
    from . import paquete
    ruta = paquete.escribir(_raiz_paquete())
    n = len(paquete.inventario(_raiz_paquete()))
    _linea("OK", f"paquete: manifiesto regenerado ({n} ficheros) en {ruta}")
    return EXIT_OK


def _cmd_paquete_verificar(args) -> int:
    """exit 0 ÍNTEGRO / exit 1 con UNA línea [FALLO] por rotura (en orden)."""
    from . import paquete
    roturas = paquete.verificar(_raiz_paquete())
    if roturas:
        for r in roturas:
            print(f"[FALLO] paquete: {r}", file=sys.stderr)
        return EXIT_FALLO
    n = len(paquete.inventario(_raiz_paquete()))
    _linea("OK", f"paquete ÍNTEGRO ({n} ficheros)")
    return EXIT_OK


def _cmd_doctor(args) -> int:
    """Comprobación post-instalación (T2, D-048): lógica en sibila/doctor.py.
    Exit 0 = SANO (avisos no penalizan), 1 = ROTO. NO es puerta del instalador
    (la puerta sigue siendo check VERDE, contrato intacto)."""
    try:
        cfg = config.load_config()
    except (config.ConfigError, OSError) as e:
        print(f"[FALLO] configuración: {e}")
        print("doctor: ROTO (1 fallos)")
        return 1
    from . import doctor as _doctor
    fallos, avisos, lineas = _doctor.doctor(cfg)
    for estado, msg in lineas:
        _linea(estado, msg)
    print(_doctor.resumen(fallos, avisos))
    return 1 if fallos else 0


def _cmd_corre(args) -> int:
    """Pipeline diario completo (T1, D-047). Sin flags: ayer UTC, reloj real."""
    from datetime import date, datetime, time as _time, timedelta, timezone
    from . import corre
    rango = _validar_rango(args.dia, args.desde, args.hasta)
    if rango is None:
        return 2
    desde, hasta = rango
    if args.fixture and (not args.dia or not args.fuente):
        print("[FALLO] --fixture exige --dia y una sola --fuente", file=sys.stderr)
        return 2
    if args.fixture_dir and (not args.desde or not args.fuente):
        print("[FALLO] --fixture-dir exige --desde y --fuente", file=sys.stderr)
        return 2
    if (args.fixture or args.fixture_dir) and args.fixture and args.fixture_dir:
        print("[FALLO] --fixture y --fixture-dir son excluyentes", file=sys.stderr)
        return 2
    if (args.fixture or args.fixture_dir) and not args.fuente:
        print("[FALLO] los fixtures exigen --fuente", file=sys.stderr)
        return 2
    cfg, ruta = _cfg_y_bd()
    if ruta is None:
        return EXIT_FALLO
    ahora = _ahora_defecto_cli()
    fallo_alerta = False

    def _anota_fallo(res):
        # rev. Hamilton M2: consistencia con `alerta enviar` (exit 1 si TODOS
        # los canales habilitados cayeron; Task Scheduler no reintenta).
        nonlocal fallo_alerta
        et = res.get("etapas", {})
        if isinstance(et.get("alerta"), dict) and et["alerta"].get("todos_caidos"):
            fallo_alerta = True

    try:
        if args.dia or (desde == hasta):
            fixtures = None
            if args.fixture:
                fixtures = {args.fuente: args.fixture}
            res = corre.ejecutar_dia(cfg, dia=desde, ahora=ahora,
                                     fixtures=fixtures,
                                     con_informe=args.con_informe,
                                     digest=args.digest)
            _anota_fallo(res)
            _linea_resumen_corre(res)
            if args.con_informe:
                _stdout_seguro()
                print(res["etapas"]["informe"]["contenido"],
                      end="" if str(res["etapas"]["informe"]["contenido"]).endswith("\n") else "\n")
        else:
            for res in corre.ejecutar_rango(
                    cfg, desde=desde, hasta=hasta, ahora=ahora,
                    fixtures_dir=args.fixture_dir, fuente=args.fuente,
                    digest_cada_domingo=args.digest):
                _anota_fallo(res)
                _linea_resumen_corre(res)
    except corre.CorreError as e:
        print(f"[FALLO] {e}", file=sys.stderr)
        return EXIT_FALLO
    if fallo_alerta:
        print("[FALLO] corre: alerta — todos los canales habilitados fallaron",
              file=sys.stderr)
        return EXIT_FALLO
    return EXIT_OK


def _linea_resumen_corre(res):
    from . import corre
    _linea("OK", corre.linea_resumen(res)[len("[OK] "):])
    for aviso in res.get("avisos", []):
        _linea("AVISO", aviso)


def _stub(args) -> int:
    print(f"{args.nombre}: no implementado en este bloque (llega en un bloque posterior)")
    return EXIT_NO_IMPLEMENTADO


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    _configurar_logging()
    args = _build_parser().parse_args(argv)  # errores de uso: SystemExit(2), argparse estándar
    try:
        return args.func(args)
    except SibilaError as e:  # errores previstos: mensaje accionable, NUNCA traceback desnudo
        print(f"[FALLO] {e}", file=sys.stderr)
        return EXIT_FALLO
    except sqlite3.Error as e:
        print(f"[FALLO] error de base de datos: {e}", file=sys.stderr)
        return EXIT_FALLO
    except KeyboardInterrupt:
        return 130
    except Exception:
        log.exception("error inesperado")
        print("[FALLO] error inesperado; detalle en logs/sibila.log", file=sys.stderr)
        return EXIT_FALLO


if __name__ == "__main__":
    raise SystemExit(main())

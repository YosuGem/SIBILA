"""Orquestador diario `sibila corre` (T1, D-047).

Secuencia NO conmutable por día: ingesta → procesa → detecta → sellar →
alerta enviar → [informe] → [digest] (procesa materializa stats; detecta
escribe signals; sellar lee signals; alerta lee signals+alert_log; digest e
informe son consumidores). Conexión FRESCA por etapa (reproduce los bordes
transaccionales de la operación real); el informe abre mode=ro propio.

Tiempo simulado (D-047 §2): `hoy = D` (date) gobierna la ventana MinHash y el
ts analítico de las métricas; `ahora = D+1T06:00:00Z` (datetime tz-aware UTC)
es la observación de corrida para created_at/cooldowns/digest. Este módulo
NO conoce el reloj real: `dia` y `ahora` son OBLIGATORIOS (el default "ayer"
vive solo en cli._cmd_corre — guardián AST C-T1).

Sin red real nunca en el arnés: los fixtures son RSS locales y `enviar` es
inyectable (None = enviar_red de alerta, solo para producción).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from . import SibilaError, db, procesa

log = logging.getLogger("sibila.corre")

ETAPAS = ("ingesta", "procesa", "detecta", "sellar", "alerta", "informe",
          "digest")


class CorreError(SibilaError):
    """Fallo de una etapa: se detiene la secuencia en esa etapa (§1.1)."""

    def __init__(self, etapa: str, detalle: str):
        super().__init__(f"corre: etapa {etapa}: {detalle}")
        self.etapa = etapa


class _ConectorFixture:
    """Conector mínimo conforme al contrato §4 de Bloque 2 para RSS local:
    fetch parsea el fixture (SIN red, SIN sesión) y devuelve (docs, None)."""

    def __init__(self, nombre: str, ruta: Path):
        self.nombre = nombre
        self.ruta = Path(ruta)
        self.cfg = {"fixture": str(self.ruta)}

    def fetch(self, cfg, cursor, **_kw):
        from .conectores import lobsters
        docs, _cont = lobsters.parsear_feed(self.ruta.read_bytes(),
                                            fuente=self.nombre)
        return docs, None


def _iso_ahora(ahora) -> str:
    if isinstance(ahora, datetime):
        if ahora.tzinfo is None or ahora.utcoffset() != timedelta(0):
            raise CorreError("orquestación", "ahora debe ser tz-aware UTC")
        return ahora.strftime("%Y-%m-%dT%H:%M:%SZ")
    raise CorreError("orquestación", f"ahora debe ser datetime UTC, no {type(ahora)}")


def ejecutar_dia(cfg, *, dia: str, ahora, fixtures=None, detector=procesa._AUTO,
                 lexicos=procesa._AUTO, enviar=None, con_informe=False, digest=False,
                 salida_informe=None) -> dict:
    """Encadena las etapas del día `dia` (YYYY-MM-DD). `fixtures`: dict
    {nombre_fuente: ruta RSS} (ausente = día hueco REAL, no error). Devuelve
    el resumen estructurado por etapa para el CLI/tests."""
    from . import alerta, detecta, informe_datos, ingesta, procesa, sella
    _iso_ahora(ahora)                       # validación temprana
    d = date.fromisoformat(dia)             # ValueError → el CLI valida antes
    resumen = {"dia": dia, "etapas": {}, "avisos": []}

    def _etapa(nombre, fn):
        con = db.connect(cfg.db_path)       # conexión fresca por etapa (§1.2)
        try:
            return fn(con)
        except SibilaError as e:
            raise CorreError(nombre, str(e)) from e
        finally:
            con.close()

    # 1 · ingesta (solo si hay fixtures del día; sin fixture = hueco real)
    nuevos = 0
    for fuente, ruta in (fixtures or {}).items():
        def _ing(con, fuente=fuente, ruta=ruta):
            return ingesta.ingestar(cfg, _ConectorFixture(fuente, ruta), None,
                                    con, hoy=ahora)
        r = _etapa("ingesta", _ing)
        nuevos += r["nuevos"]
        resumen["etapas"][f"ingesta:{fuente}"] = r
    resumen["ingesta_nuevos"] = nuevos

    # 2 · procesa (hoy = día analítico: ventana MinHash + ts de métricas)
    r = _etapa("procesa", lambda con: procesa.ejecutar(
        cfg, con, dia=dia, hoy=d, detector=detector, lexicos=lexicos))
    resumen["etapas"]["procesa"] = r
    resumen["avisos"].extend(r.get("avisos", []))

    # 2b · anti falso-éxito (ALTO-1): si el DÍA produjo documentos procesados
    # y TODOS quedaron con lang NULL, no hubo analítica de idioma real: el día
    # no puede ser verde. La consulta se limita al día (un histórico sano no
    # debe tapar un fallo de hoy, ni uno viejo ensuciar un día bueno). Un día
    # sin documentos (hueco real) sigue siendo éxito legítimo. El control se
    # evalúa siempre — también en reejecuciones sin pendientes — de modo que
    # un día degradado queda ROJO hasta su remediación con `procesa --todo`.
    try:
        con = db.connect(cfg.db_path)
        try:
            fila = con.execute(
                "SELECT COUNT(*) AS n, SUM(lang IS NULL) AS nulos"
                " FROM documents WHERE dia = ?"
                " AND calidad_score IS NOT NULL", (dia,)).fetchone()
        finally:
            con.close()
    except SibilaError:
        raise
    except Exception as e:
        raise CorreError("procesa", f"no se pudo verificar la analítica del día: {e}") from e
    if fila["n"] > 0 and fila["nulos"] == fila["n"]:
        raise CorreError(
            "procesa", "procesamiento analítico no realizado: todos los "
            "documentos del día quedaron sin idioma (recursos de idioma "
            "ausentes o textos no clasificables). Remediación: con los "
            "recursos disponibles, ejecuta 'sibila procesa --todo' y repite "
            "el día")

    # 3 · detecta (created_at/observación = ahora; ts de métricas = día)
    r = _etapa("detecta", lambda con: detecta.ejecutar(cfg, con, dia=dia,
                                                       ahora=ahora))
    resumen["etapas"]["detecta"] = r
    resumen["avisos"].extend(r.get("avisos", []))

    # 4 · sellar (nunca alertar sin sellar: orden congelado)
    r = _etapa("sellar", lambda con: sella.ejecutar(cfg, con, dia=dia,
                                                    ahora=ahora))
    resumen["etapas"]["sellar"] = r

    # 5 · alerta enviar (red FUERA de tx dentro de alerta; enviar inyectable)
    r = _etapa("alerta", lambda con: alerta.ejecutar(cfg, con, desde=dia,
                                                     hasta=dia, ahora=ahora,
                                                     enviar=enviar))
    resumen["etapas"]["alerta"] = r

    # 6 · informe (opcional, ro puro; A-T1-1: bajo demanda, no en la corrida)
    if con_informe:
        def _inf(_con):
            con_ro = informe_datos.conectar_ro(cfg.db_path)
            try:
                return informe_datos.ejecutar(cfg, con_ro, desde=dia, hasta=dia,
                                              ahora=ahora)
            finally:
                con_ro.close()
        r = _etapa("informe", _inf)
        resumen["etapas"]["informe"] = r
        if salida_informe:
            informe_datos.escribir_fichero(salida_informe, r["contenido"],
                                           r["meta"])

    # 7 · digest de la semana ISO que CONTIENE el día (--digest)
    if digest:
        lunes, domingo = informe_datos.semana_iso(d)
        r = _etapa("digest", lambda con: alerta.digest(
            cfg, con, desde=lunes, hasta=domingo, ahora=ahora, enviar=enviar))
        resumen["etapas"]["digest"] = r
    return resumen


def ejecutar_rango(cfg, *, desde: str, hasta: str, ahora, fixtures_dir=None,
                   fuente: str | None = None, detector=procesa._AUTO, lexicos=procesa._AUTO,
                   enviar=None, digest_cada_domingo=False) -> list:
    """Multi-día ASC. Con --fixture-dir lee `{dia}.xml` por día; un día sin
    fichero es día hueco REAL (no error silencioso, §1.1). `ahora` es el
    instante de la PRIMERA jornada; cada día posterior usa ahora+i·24 h."""
    dias = []
    d0, d1 = date.fromisoformat(desde), date.fromisoformat(hasta)
    d = d0
    while d <= d1:
        fixtures = None
        if fixtures_dir is not None and fuente is not None:
            ruta = Path(fixtures_dir) / f"{d.isoformat()}.xml"
            if ruta.exists():
                fixtures = {fuente: ruta}
        dias.append(d.isoformat())
        d += timedelta(days=1)
    resumenes = []
    for i, dia in enumerate(dias):
        fixtures = None
        if fixtures_dir is not None and fuente is not None:
            ruta = Path(fixtures_dir) / f"{dia}.xml"
            if ruta.exists():
                fixtures = {fuente: ruta}
        ahora_d = ahora + timedelta(days=i)
        es_domingo = date.fromisoformat(dia).weekday() == 6
        resumenes.append(ejecutar_dia(
            cfg, dia=dia, ahora=ahora_d, fixtures=fixtures, detector=detector,
            lexicos=lexicos, enviar=enviar, digest=digest_cada_domingo and es_domingo))
    return resumenes


def linea_resumen(r: dict) -> str:
    """Línea compacta del CLI (§1.2)."""
    det = r["etapas"].get("detecta", {})
    sel = r["etapas"].get("sellar", {})
    ale = r["etapas"].get("alerta", {})
    c = ale.get("contadores", {}) if isinstance(ale, dict) else {}
    return (f"[OK] corre {r['dia']}: ingesta {r['ingesta_nuevos']} nuevos · "
            f"procesa {r['etapas'].get('procesa', {}).get('contadores', {}).get('procesados', 0)} · "
            f"detecta {det.get('alertas', 0) if isinstance(det, dict) else 0} alertas · "
            f"registro {sel.get('contadores', {}).get('selladas', 0) if isinstance(sel, dict) else 0} selladas · "
            f"alerta {c.get('enviadas', 0)} enviadas")

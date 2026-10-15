"""Render PURO del informe (spec §9, D-T7-5…8). Byte-exacto: el vector (i) §4.1
fija 620 bytes UTF-8 + SHA-256 (doble ancla). Determinista (TP-N4): el render
ORDENA (T-B7-1) — la capa de datos entrega crudo.

Estructura FIJA de 7 secciones, siempre completas (día hueco incluido:
D-T7-8, T-B7-4). Marcadores estructurales ASCII puro (cp1252; "·" vetado,
T-B7-3); contenido de temas pasa tal cual. Separador de campos " | ". Sin
líneas en blanco interiores; la salida termina en exactamente un "\\n"
(lección D-044, T-B7-2).

CORRECCIÓN DE CONTRATO (Bloque 7, decisión del Orquestador): la primera
entrega omitió `render_csv`/`render_json`, que el §5 del plan de datos
(Liskov) promete y el CLI ya ofrece (`--formato json|csv`). Se AÑADEN aquí
sobre el MISMO DatosInforme: CSV vía csv stdlib con CRLF (\\r\\n es lo
CORRECTO en CSV — RFC 4180; contraste documentado con el LF del registro) y
JSON determinista vía canonical_json del Bloque 6. Ausencia → "n/d", jamás 0
(TP-N12).
"""
import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal

INFORME_VERSION = "informe-1"   # versión del algoritmo de render (cambio = vectores nuevos)

from ..alertas.reglas import ORDEN_NIVEL, mapear_tema
from ..registro.canonico import canonical_json

_SIN_VAR = "(sin variaciones)"


@dataclass(frozen=True)
class DatosInforme:
    """TODO dato, cero consultas; lo monta la capa de datos.
    DESVIACIÓN documentada del §3 del plan: se añade `etiquetas` (dict
    cluster:{hex16}→texto) porque D-T7-7 ordena al RENDER mapear hex→etiqueta
    y el dataclass listado no lo traía; opcional con {} por defecto."""
    dia: str                   # 'YYYY-MM-DD' o rango ya formateado
    docs: int
    fuentes_on: int
    fuentes_total: int
    dups: int
    excl_fecha: int
    elegibles: int
    ciegos: int
    parcial: bool
    hueco: bool
    inmaduro: bool
    sube: tuple                # ((tema, z_r_str), …) crudo: el render ordena
    baja: tuple
    emergentes: tuple
    alertas: tuple             # líneas ya formateadas por alertas_fmt()
    anomalias: tuple
    pend: int
    pend_inm: int
    resueltas: int
    gdelt: str                 # "n/d" jamás 0 (TP-N12, T-B7-5)
    etiquetas: dict = field(default_factory=dict)


def _si_no(b: bool) -> str:
    return "si" if b else "no"


def _z(x: str) -> Decimal:
    return abs(Decimal(x))


def render_informe(d: DatosInforme) -> str:
    """DatosInforme → texto UTF-8 byte-exacto. ValueError si falta un campo
    (None) o los tipos no son los del contrato. TODOS los campos obligatorios
    se validan (rev. Dijkstra M6: docs=None renderizaba 'None' en silencio);
    fuentes_total admite int o la cadena 'n/d' (degradado visible, M4)."""
    for nombre in ("dia", "docs", "fuentes_on", "fuentes_total", "dups",
                   "excl_fecha", "elegibles", "ciegos", "parcial", "hueco",
                   "inmaduro", "sube", "baja", "emergentes", "alertas",
                   "anomalias", "pend", "pend_inm", "resueltas", "gdelt"):
        if getattr(d, nombre) is None:
            raise ValueError(f"falta campo obligatorio: {nombre}")
    anomalias = list(d.anomalias)

    def _mapear(tema: str) -> str:
        txt, ok = mapear_tema(tema, d.etiquetas)
        if not ok:
            anomalias.append(f"cluster sin etiqueta: {tema}")  # T-B7-10
        return txt

    L = [f"[OK] informe: dia {d.dia}", "== Resumen ==",  # cabecera + Resumen
         f"documentos: {d.docs} (fuentes activas: {d.fuentes_on}/{d.fuentes_total})",
         f"duplicados: {d.dups} | excluidos por fecha: {d.excl_fecha}",
         f"items elegibles: {d.elegibles} | items ciegos: {d.ciegos}",
         f"dia parcial: {_si_no(d.parcial)} | dia hueco: {_si_no(d.hueco)} | "
         f"mes inmaduro: {_si_no(d.inmaduro)}",
         "== Tension =="]
    # D-T7-5: Tension por |z_r| DESC, desempate texto ASC (el render ordena)
    sube = sorted(d.sube, key=lambda t: (-_z(t[1]), t[0]))
    baja = sorted(d.baja, key=lambda t: (-_z(t[1]), t[0]))
    L += [f"sube: {_mapear(t)} (z_r {z})" for t, z in sube] or \
        ([f"sube: {_SIN_VAR}"] if baja else [_SIN_VAR])
    L += [f"baja: {_mapear(t)} (z_r {z})" for t, z in baja] or \
        ([f"baja: {_SIN_VAR}"] if sube else [])
    L.append("== Emergentes ==")
    L += [f"- {_mapear(t)}" for t in sorted(d.emergentes)] or ["(ninguno)"]
    L.append("== Alertas ==")
    # D-T7-5: nivel alarma>alerta>vigilancia primero, luego texto ASC. El
    # nivel va en el prefijo [NIVEL] de la línea formateada por alertas_fmt.
    def _clave_alerta(linea: str):
        tag = linea.split("]", 1)[0].lstrip("[").lower()
        return (-ORDEN_NIVEL.get(tag, 0), linea)
    L += sorted(d.alertas, key=_clave_alerta) or ["(ninguna)"]
    L.append("== Anomalias ==")
    L += anomalias or ["(ninguna)"]
    L.append("== Predicciones ==")
    L.append(f"pendientes: {d.pend} (inmaduras: {d.pend_inm}) | "
             f"resueltas: {d.resueltas}")
    L.append(f"cobertura GDELT: {d.gdelt}")
    L.append("== Exportacion ==")
    L.append(f"CSV: informe_{d.dia}.csv | JSON: informe_{d.dia}.json")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# Exportación CSV/JSON (corrección de contrato §5-Liskov; ver cabecera).
# Misma semántica de ordenación/mapeo que render_informe (D-T7-5/7).
# ---------------------------------------------------------------------------

def _ordenados(d: DatosInforme):
    """(sube, baja, emergentes, alertas) ordenados como el md."""
    sube = sorted(d.sube, key=lambda t: (-_z(t[1]), t[0]))
    baja = sorted(d.baja, key=lambda t: (-_z(t[1]), t[0]))
    emer = sorted(d.emergentes)

    def _clave_alerta(linea: str):
        tag = linea.split("]", 1)[0].lstrip("[").lower()
        return (-ORDEN_NIVEL.get(tag, 0), linea)

    return sube, baja, emer, sorted(d.alertas, key=_clave_alerta)


def _vista(d: DatosInforme) -> dict:
    """Vista dict determinista del informe (mapeo hex→etiqueta aplicado;
    hex sin etiqueta queda crudo y se anota en anomalias, D-T7-7/T-B7-10)."""
    sube, baja, emer, alertas = _ordenados(d)
    anomalias = list(d.anomalias)

    def _m(tema: str) -> str:
        txt, ok = mapear_tema(tema, d.etiquetas)
        if not ok:
            anomalias.append(f"cluster sin etiqueta: {tema}")
        return txt

    return {
        "dia": d.dia,
        "resumen": {
            "documentos": d.docs,
            "fuentes_activas": f"{d.fuentes_on}/{d.fuentes_total}",
            "duplicados": d.dups,
            "excluidos_por_fecha": d.excl_fecha,
            "items_elegibles": d.elegibles,
            "items_ciegos": d.ciegos,
            "dia_parcial": _si_no(d.parcial),
            "dia_hueco": _si_no(d.hueco),
            "mes_inmaduro": _si_no(d.inmaduro),
        },
        "tension": {"sube": [[_m(t), z] for t, z in sube],
                    "baja": [[_m(t), z] for t, z in baja]},
        "emergentes": [_m(t) for t in emer],
        "alertas": list(alertas),
        "anomalias": anomalias,
        "predicciones": {"pendientes": d.pend, "inmaduras": d.pend_inm,
                         "resueltas": d.resueltas,
                         "cobertura_gdelt": d.gdelt},
        "version": INFORME_VERSION,
    }


def render_csv(d: DatosInforme) -> str:
    """CSV plano (seccion, clave, valor) con \\r\\n (csv stdlib, RFC 4180 — el
    CRLF es CORRECTO aquí, a diferencia del LF del JSONL del registro).
    Determinista (mismo orden que el md). Secciones de lista vacías no emiten
    filas (el CSV es datos; la estructura siempre-presente es del md).
    Formato CONGELADO por los vectores de tests/test_informe_export.py."""
    v = _vista(d)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["seccion", "clave", "valor"])
    for clave, valor in v["resumen"].items():
        w.writerow(["resumen", clave, valor])
    for tema, z in v["tension"]["sube"]:
        w.writerow(["tension_sube", tema, z])
    for tema, z in v["tension"]["baja"]:
        w.writerow(["tension_baja", tema, z])
    for t in v["emergentes"]:
        w.writerow(["emergentes", t, ""])
    for linea in v["alertas"]:
        w.writerow(["alertas", "", linea])
    for linea in v["anomalias"]:
        w.writerow(["anomalias", "", linea])
    for clave, valor in v["predicciones"].items():
        w.writerow(["predicciones", clave, valor])
    w.writerow(["meta", "version", v["version"]])
    return buf.getvalue()


def render_json(d: DatosInforme) -> bytes:
    """JSON canónico (canonical_json del Bloque 6: claves ordenadas,
    separadores compactos, UTF-8 sin escapar no-ASCII). Determinista por
    construcción; la vista es la misma que el CSV."""
    return canonical_json(_vista(d))

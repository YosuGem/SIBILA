"""Severidad y formato de alertas (D-T7-2/3, RATIFICADAS por el Orquestador).

Qué es alertable (D-T7-2): solo señales 'confirmado' o 'inmaduro' del día; las
inmaduras SÍ se notifican marcadas [INMADURO] (no computan para el veredicto).
'vigilancia' = tensión sin conjunción (racha insuficiente o MK/CUSUM sin
cerrar): vive SOLO en digest/informe, sin envío inmediato ni cooldown
individual (M2-Liskov; T-B7-17).
"""
from dataclasses import dataclass
from decimal import Decimal

NIVELES = ("vigilancia", "alerta", "alarma")
ORDEN_NIVEL = {"vigilancia": 0, "alerta": 1, "alarma": 2}

UMBRAL_ALARMA_ZR = Decimal("6.0000")   # doble del umbral de alerta (D-T7-3)
ALFA_MK = Decimal("0.05")              # conjunción: p_mk < 0,05 (estricto)
H_CUSUM = Decimal("4")                 # conjunción: S > h (=4, spec §7)


@dataclass(frozen=True)
class ContextoDia:               # campos CONGELADOS (plan §2)
    z_r: "Decimal | None"
    p_mk: "Decimal | None"
    s_cusum: "Decimal | None"
    racha_z: int
    status: str                  # 'confirmado' | 'inmaduro'
    alertas_previas_tema_7d: int


@dataclass(frozen=True)
class Senal:                     # la tupla que entrega la capa de datos
    tema: str
    target_type: str             # 'term'|'bigram'|'trigram'|'cluster'|'emocion'
    status: str
    day: object                  # date


def clasificar(senal: Senal, contexto: ContextoDia) -> "str | None":
    """'vigilancia'|'alerta'|'alarma'|None (no notificar). Sin reloj.

    - status fuera de {confirmado, inmaduro} → None (D-T7-2).
    - Conjunción completa (racha≥3 ∧ p_mk<0,05 ∧ S_CUSUM>4): 'alarma' si
      confirmado ∧ (z_r ≥ 6,0000 ∨ segunda alerta del tema en ≤7 días);
      si no, 'alerta'. Las inmaduras NUNCA escalan (tope 'alerta' — T-B7-9).
    - Sin conjunción pero con z_r>3 (racha 1-2 o MK/CUSUM sin cerrar):
      'vigilancia'. En otro caso, None.
    """
    if senal.status not in ("confirmado", "inmaduro"):
        return None
    c = contexto
    conjuncion = (c.racha_z >= 3 and c.p_mk is not None
                  and c.p_mk < ALFA_MK and c.s_cusum is not None
                  and c.s_cusum > H_CUSUM)
    if conjuncion:
        if (senal.status == "confirmado" and c.z_r is not None
                and (c.z_r >= UMBRAL_ALARMA_ZR
                     or c.alertas_previas_tema_7d >= 1)):
            return "alarma"
        return "alerta"
    if c.z_r is not None and c.z_r > 3:
        return "vigilancia"
    return None


def mapear_tema(tema: str, etiquetas: dict) -> "tuple[str, bool]":
    """Mapeo hex→etiqueta (D-T7-7, A-B6-7): 'cluster:{hex16}' →
    'etiqueta (cluster:{hex16})' si hay etiqueta; si no, el hex CRUDO y
    False (el llamador lo anota en Anomalías — nunca desaparece en silencio,
    T-B7-10). 'emocion:{lang}' → 'emocion ({lang})'. Resto: se devuelve el
    tema tal cual con True (la capa añade el origen si quiere)."""
    if tema.startswith("cluster:"):
        etq = etiquetas.get(tema)
        if etq:
            return f"{etq} ({tema})", True
        return tema, False
    if tema.startswith("emocion:"):
        return f"emocion ({tema.split(':', 1)[1]})", True
    return tema, True


def _campo(obj, nombre, defecto=None):
    return obj.get(nombre, defecto) if isinstance(obj, dict) \
        else getattr(obj, nombre, defecto)


def _fmt_num(x) -> str:
    """Marcador a 4 dec: Decimal → str tal cual; float → .4f; None → 'n/d'."""
    if x is None:
        return "n/d"
    if isinstance(x, Decimal):
        return str(x)
    return f"{float(x):.4f}"


def alertas_fmt(senal, nivel: str, etiquetas: dict,
                contexto: "ContextoDia | None" = None, *,
                z_r=None, p_mk=None, s_cusum=None) -> str:
    """Línea ÚNICA de alerta (compartida alerta↔informe, T-B7-13):
    `[NIVEL] [INMADURO] tema (origen): z_r … | MK p … | CUSUM … (status)`.
    Las inmaduras llevan la marca [INMADURO] (D-T7-2). Marcadores ASCII puro
    (T-B7-3).
    NOTA de contrato (informe Bloque 7): el plan §3 listaba la firma nominal
    `(senal, nivel, etiquetas)`, imposible para emitir z_r/MK/CUSUM (Senal no
    los lleva). Firma efectiva CONVENIDA: los marcadores llegan vía
    `contexto` (4.º posicional, ContextoDia) o vía kwargs `z_r=/p_mk=/s_cusum=`
    (uso de la capa de datos). `senal` acepta Senal o dict equivalente.
    ValueError si nivel desconocido."""
    if nivel not in ORDEN_NIVEL:
        raise ValueError(f"nivel desconocido: {nivel!r}")
    if contexto is not None:
        z_r, p_mk, s_cusum = contexto.z_r, contexto.p_mk, contexto.s_cusum
    status = _campo(senal, "status")
    marca = " [INMADURO]" if status == "inmaduro" else ""
    tema_txt, _ = mapear_tema(_campo(senal, "tema", ""), etiquetas)
    return (f"[{nivel.upper()}]{marca} {tema_txt}: "
            f"z_r {_fmt_num(z_r)} | MK p {_fmt_num(p_mk)} | "
            f"CUSUM {_fmt_num(s_cusum)} ({status})")

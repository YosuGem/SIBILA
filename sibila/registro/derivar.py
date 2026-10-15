"""Derivación señales → borradores de predicción (regla D-T6-6, determinista
y conservadora; A-B6-3 CERRADA por el Orquestador).

SOLO las señales metric='z_r' generan predicción: las filas cusum/mk del mismo
ítem son EVIDENCIA de la alerta (spec §9), no predicciones independientes —
sellar 3 por ítem inflaría el denominador del veredicto (D-011) con
triplicados correlados (T-B6-9).
"""
from dataclasses import dataclass
from decimal import Decimal

# Constantes CONGELADAS de Fase 1 (D-T6-6). El criterio NO interpola el tema
# (T-B6-10: interpolarlo lo haría irreconocible para el resolvedor; el tema va
# en su propio campo). Comparadores ASCII ("<=", ">=") deliberados.
UMBRAL_ZR = "3.0000"
VENTANA_FASE1 = "P7D"
CRITERIO_ACIERTO = "z_r>3.0000 en >=1 dia de los 7 siguientes"

_METRICAS_SENAL = frozenset({"z_r", "cusum", "mk"})
_STATUS_SENAL = frozenset({"confirmado", "inmaduro"})


@dataclass(frozen=True)
class BorradorPrediccion:      # firma de Liskov §3, aceptada íntegra
    tema: str
    metrica: str
    umbral: str
    ventana: str
    criterio_acierto: str


@dataclass(frozen=True)
class Senal:
    target_type: str           # 'term'|'bigram'|'trigram'|'cluster'|'emocion'
    target: str                # texto del ítem (terms.text)
    metric: str                # 'z_r'|'cusum'|'mk'
    score: Decimal
    status: str                # 'confirmado'|'inmaduro'
    day: object                # date


def _validar(s: Senal) -> None:
    """ValueError (fallo visible, diseño deliberado) ante señal mal formada:
    metric/status fuera de dominio, target vacío, score no Decimal. La capa de
    datos filtra status ANTES; si le llega otro, este ValueError la delata."""
    if s.metric not in _METRICAS_SENAL:
        raise ValueError(f"metric desconocida: {s.metric!r}")
    if s.status not in _STATUS_SENAL:
        raise ValueError(f"status desconocido: {s.status!r}")
    if not isinstance(s.target, str) or not s.target:
        raise ValueError("target vacío")
    if not isinstance(s.score, Decimal):
        raise ValueError("score debe ser Decimal (D-T6-1)")


def derivar(senales: tuple, dia) -> tuple:
    """Un borrador por cada señal z_r elegible; cusum/mk se omiten EN SILENCIO
    (no es error: es la regla D-T6-6). Orden de salida = orden de entrada (la
    pura NO reordena — T-B6-11). `dia` se reserva para reglas futuras (hoy no
    modifica nada; es parámetro para que el reloj nunca entre por detrás)."""
    out = []
    for s in senales:
        _validar(s)
        if s.metric != "z_r":
            continue
        out.append(BorradorPrediccion(
            tema=s.target, metrica="z_r", umbral=UMBRAL_ZR,
            ventana=VENTANA_FASE1, criterio_acierto=CRITERIO_ACIERTO))
    return tuple(out)

"""Cooldown/dedup de alertas (D-T7-4, RATIFICADA por el Orquestador).

El historial SOLO contiene envíos REALES: la capa de datos registra los
intentos fallidos con canal='fallo:{canal}' y los FILTRA antes de entregar el
historial (B1 compartido) — un fallo NUNCA enfría (T-B7-15, test cruzado).
Borde exacto (N1-Liskov): cooldown vigente mientras (ahora − último) <
ventana; en el borde EXACTO (== ventana) → PERMITIDA (T-B7-16).
"""
from dataclasses import dataclass
from datetime import timedelta

from .reglas import ORDEN_NIVEL

# Ventanas por nivel (D-T7-4): vigilancia n/a (solo digest, T-B7-17);
# el digest tiene 168 h por construcción (uno por semana).
VENTANAS = {"alerta": timedelta(hours=72), "alarma": timedelta(hours=24)}


@dataclass(frozen=True)
class Envio:
    """Envío REAL registrado (orden ASC por sent_at lo da la capa de datos;
    la pura NO reordena)."""
    tema: str
    nivel: str                 # 'alerta'|'alarma'
    sent_at: object            # datetime tz-aware UTC


@dataclass(frozen=True)
class Decision:
    enviar: bool
    motivo: str


def decidir(tema: str, nivel: str, historial: tuple, ahora) -> Decision:
    """Cooldown por (tema, nivel) con escalada/desescalada (D-T7-4).

    - Escalada (nivel superior al de la ÚLTIMA alerta enviada del tema) →
      siempre permitida (T-B7-8).
    - Mismo nivel o desescalada → cooldown del nivel NUEVO contra el último
      envío DE ESE NIVEL (T-B7-7): permitida si (ahora − último) >= ventana
      (borde exacto permitido, comparación estricta `<` — T-B7-16).
    - 'vigilancia' NO tiene cooldown individual: ValueError (T-B7-17; la
      digest la maneja aparte). ValueError también en nivel desconocido.
    """
    if nivel not in VENTANAS:
        raise ValueError(f"nivel sin cooldown individual: {nivel!r}")
    previos = [e for e in historial if e.tema == tema]
    if previos and ORDEN_NIVEL[nivel] > ORDEN_NIVEL[previos[-1].nivel]:
        return Decision(True, "escalada")
    mismo = [e for e in previos if e.nivel == nivel]
    if not mismo:
        return Decision(True, "nueva")
    delta = ahora - mismo[-1].sent_at
    if delta < VENTANAS[nivel]:
        return Decision(False, "cooldown")
    return Decision(True, "cooldown vencido")


def dedup_alertas(nuevas: tuple, historial: tuple, ahora) -> tuple:
    """(emitir, suprimidas) — (tema, nivel) en ORDEN DE LLEGADA preservado
    (T-B7-14). Itera decidir añadiendo cada envío emitido al historial
    efectivo de los siguientes. 'vigilancia' no consulta historial: se emite
    siempre (vive solo en el digest, D-T7-3/T-B7-17)."""
    emitir = []
    suprimidas = []
    efectivo = list(historial)
    for tema, nivel in nuevas:
        if nivel == "vigilancia":
            emitir.append((tema, nivel))
            continue
        d = decidir(tema, nivel, tuple(efectivo), ahora)
        if d.enviar:
            emitir.append((tema, nivel))
            efectivo.append(Envio(tema, nivel, ahora))
        else:
            suprimidas.append((tema, nivel))
    return tuple(emitir), tuple(suprimidas)

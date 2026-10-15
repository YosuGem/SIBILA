"""Motor puro de la conjunción del gate G1 (spec §7, párrafo ALERTA).

Fachada estadística SIN status (rev. cruzada E1/N1): el status
('confirmado'/'inmaduro') es DECISIÓN DE DATOS de detecta.py a partir de
dias_historia (días de calendario desde el primer día con stats en la BD —
definición congelada, A-B5-1); no entra en `evaluar` porque no es estadística.
Todo parámetro es dato; ninguna consulta a nada (puro; sin reloj: T-B5-13).
"""
from dataclasses import dataclass
from decimal import Decimal

from .cusum import cusum
from .pendiente import mann_kendall, theil_sen
from .series import baseline_dow, u_t, z_r

ALFA = Decimal("0.05")          # p < 0,05 ESTRICTO (T-B5-15: 0,0500 no alerta)
UMBRAL_RACHA = Decimal("3")     # z_r > 3 (spec §7)
RACHA_MIN = 3


@dataclass(frozen=True)
class Veredicto:
    alerta: bool
    racha: int      # días consecutivos computables con z_r > 3 terminando en t
    motivo: str     # qué cláusula falló o disparó (auditoría: siempre relleno)


def racha_alta(zrs: list, umbral: Decimal = UMBRAL_RACHA) -> int:
    """Días consecutivos con z > umbral contados hacia atrás desde el último.
    Un None (día ciego/hueco) ROMPE la racha (spec §7 — T-B5-12); un valor
    ≤ umbral también. Devuelve la longitud de la racha final."""
    r = 0
    for z in reversed(zrs):
        if z is None or not (z > umbral):
            break
        r += 1
    return r


def conjuncion(elegible: bool, zrs: list, p_mk, cusum_cruce_en_racha: bool,
               parcial: bool) -> Veredicto:
    """Conjunción del gate: elegibilidad ∧ racha ≥ 3 ∧ p_mk < 0,05 ∧ cruce de
    CUSUM dentro de la racha. `parcial` (A-4) → sin alerta y la capa de datos
    NO escribe nada del día (trampa T-B5-19). p_mk=None (ventana MK
    incompleta, D-T5-7) → no alerta. `cusum_cruce_en_racha` lo calcula el
    llamador (esta función no hace aritmética de índices)."""
    if parcial:
        return Veredicto(False, racha_alta(zrs), "dia parcial")
    if not elegible:
        return Veredicto(False, racha_alta(zrs), "no elegible")
    racha = racha_alta(zrs)
    if racha < RACHA_MIN:
        return Veredicto(False, racha, "racha insuficiente")
    if p_mk is None:
        return Veredicto(False, racha, "mk no computable")
    if not (p_mk < ALFA):
        return Veredicto(False, racha, "mk no significativo")
    if not cusum_cruce_en_racha:
        return Veredicto(False, racha, "cusum sin cruce en racha")
    return Veredicto(True, racha, "alerta")


@dataclass(frozen=True)
class EvalItem:
    """Resultado puro de UN ítem en UN día (contrato §3, D-041). SIN status
    (E1: el status 'confirmado'/'inmaduro' lo decide la capa de datos a partir
    de dias_historia; no es estadística)."""
    z_r: "Decimal | None"        # 4 dec. HALF_UP; None si día ciego/hueco
    s_cusum: "Decimal | None"    # S_t del día evaluado (4 dec.)
    p_mk: "Decimal | None"       # None si ventana MK incompleta (D-T5-7) o Var=0
    pendiente: "Decimal | None"  # Theil-Sen con posiciones de calendario (N5)
    racha_z: int                 # días consecutivos computables z_r>3 hasta t
    cusum_cruza: bool            # cruce de h dentro de los días de la racha
    alerta: bool                 # elegible ∧ racha≥3 ∧ p<0,05 ∧ cusum_cruza


def evaluar(serie, *, elegible: bool) -> EvalItem:
    """Fachada pura por ítem/día (contrato §3/§6): recibe la SerieDiaria
    t−56…t completa y orquesta las primitivas (baseline_dow con la baseline
    rodante de SU día — T-B5-1 —, z_r, u_t, cusum, mann_kendall, theil_sen).
    Ninguna consulta a reloj/BD/ficheros: el día evaluado es el último de la
    serie. Nunca lanza por datos: lo no computable es None.

    D-042 (rev. Dijkstra B1, bloqueante): la ELEGIBILIDAD es DATO DE ENTRADA,
    no se deriva de los valores de la serie. `series.elegible` (media ≥5 de
    los 28 días previos) solo tiene sentido para conteos de documentos
    (términos/clústeres); aplicada a valence ∈ [−1,1] la haría inalcanzable.
    La capa de datos la calcula por carril: `elegible()` para términos; para
    emoción, el gate n_efectivo ≥ MIN_N_EFECTIVO_EMO del día evaluado."""
    vals = serie.valores
    n = len(vals)                       # 57 (validado en SerieDiaria)
    fechas = serie.fechas
    bases = [baseline_dow(serie, i) for i in range(n)]

    def _zr(i):
        if vals[i] is None or bases[i].ciego:
            return None
        return z_r(vals[i], bases[i])

    zrs = [_zr(i) for i in range(n)]
    racha = racha_alta(zrs)

    # CUSUM sobre t−28…t (índices n−29…n−1); cada u_i con la baseline de SU
    # día i (D-T5-5); hueco (x None) → u None → skip (D-T5-1/D-T5-6).
    us = [None if vals[i] is None else u_t(vals[i], bases[i])
          for i in range(n - 29, n)]
    rc = cusum(us)
    s_t = rc.s[-1] if rc.s else None
    # El cruce cae dentro de la racha si su índice global ∈ [n−racha, n−1].
    cruza = (rc.cruce is not None and racha > 0
             and (n - 29 + rc.cruce) >= n - racha)

    # MK / Theil-Sen SOLO con ventana t−27…t COMPLETA (28 no-None, D-T5-7);
    # serie constante (Var=0) → no computable, jamás alerta (§3.3).
    ventana = vals[n - 28:]
    if any(v is None for v in ventana):
        p_mk = pend = None
    else:
        try:
            p_mk = mann_kendall(list(ventana)).p
        except ValueError:
            p_mk = None
        try:
            pend = theil_sen([f.toordinal() for f in fechas[n - 28:]],
                             list(ventana))
        except ValueError:
            pend = None

    v = conjuncion(elegible, zrs, p_mk, cruza, False)
    return EvalItem(z_r=zrs[-1], s_cusum=s_t, p_mk=p_mk, pendiente=pend,
                    racha_z=racha, cusum_cruza=cruza, alerta=v.alerta)

"""Series temporales: calendario, baseline rodante por día de semana,
mediana/MAD, z_r, u_t, elegibilidad y día parcial (spec §7, D-T5-1..7).

Contratos transversales:
- Día = datetime.date UTC; weekday() de Python (lunes=0).
- Serie = list[tuple[date, float|None]] ordenada estricta, días únicos;
  None = HUECO (día sin corpus); un día con corpus donde el ítem no aparece
  es x=0.0 real, NO hueco (D-T5-1).
- Centinela "no computable" = None, jamás excepción ni 0.0 (D-T5-4).
- Ventana baseline = t−28…t−1 filtrada al weekday de t (D-T5-5): la fila del
  propio día JAMÁS se lee (sin look-ahead, trampa T-B5-7).
- Día ciego: n<4 observaciones del weekday o MAD=0 (D-T5-6).
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

K_ZR = 0.6745      # constante de consistencia gaussiana (spec §7)
K_SIGMA = 1.4826   # MAD → σ robusta
_C4 = Decimal("0.0001")

#: Centinela de `serie_dia`: el día NO está presente en la serie (a distinguir
#: de valor None explícito = hueco, y de 0.0 = ausencia real del ítem).
AUSENTE = object()


def _dec4(x: float) -> Decimal:
    """Cuantizado final 4 dec. HALF_UP sobre el float crudo (D-T5-3)."""
    return Decimal(str(x)).quantize(_C4, ROUND_HALF_UP)


@dataclass(frozen=True)
class Baseline:
    """Baseline rodante del weekday. `mediana`/`mad` a 4 dec. HALF_UP;
    None = día ciego (n<4 o MAD=0; en MAD=0 la mediana SE CONSERVA para el
    informe — vector (ñ) — y `mad` es None)."""
    mediana: "Decimal | None"
    mad: "Decimal | None"
    n: int                    # observaciones del weekday en la ventana (0..4)
    ciego: bool


def mediana(xs: list) -> float:
    """Mediana estándar; n par → media de los dos centrales (T-B5-9).
    Implantación propia (congelada, sin statistics) para control total del
    caso par. ValueError si la lista está vacía."""
    if not xs:
        raise ValueError("mediana de lista vacía")
    s = sorted(xs)
    n = len(s)
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2


def mad(xs: list) -> float:
    """MAD = mediana(|x − mediana(xs)|). Misma política par/impar que mediana."""
    m = mediana(xs)
    return mediana([abs(x - m) for x in xs])


DIAS_SERIE = 57  # t−56…t: la recursión CUSUM empieza en t−28 y la baseline de
                 # ESE día abarca t−56…t−29 (rev. cruzada B2; con 29 posiciones
                 # la rampa congelada da S falsos — demostrado por Turing)


@dataclass(frozen=True)
class SerieDiaria:
    """Serie de UN ítem para evaluar UN día (contrato §3, D-041).

    dias: tupla de 'YYYY-MM-DD' ASC de calendario CONTINUO t−56…t (57
    posiciones exactas). valores: tupla paralela float | None, MATERIALIZADA
    por la capa de datos (D-B5-04): 0.0 = día CON corpus donde el ítem no
    aparece (observación real de ausencia); None = día HUECO (sin NINGÚN
    documento ese día) o fuera de historia. Hueco ≠ 0 (T-B5-10). El día
    parcial entra con su valor real (A-4 cerrada: sin exclusión circular).
    ValueError (error de programación, nunca por datos): longitudes
    distintas, != 57 posiciones, fechas no ISO, o calendario no continuo ASC.
    """
    dias: tuple
    valores: tuple

    def __post_init__(self):
        if len(self.dias) != len(self.valores):
            raise ValueError("dias y valores deben tener la misma longitud")
        if len(self.dias) != DIAS_SERIE:
            raise ValueError(f"la serie debe tener {DIAS_SERIE} posiciones "
                             "(t−56…t)")
        fechas = []
        for d in self.dias:
            try:
                fechas.append(date.fromisoformat(d))
            except (TypeError, ValueError):
                raise ValueError(f"día no ISO 'YYYY-MM-DD': {d!r}") from None
        for i in range(1, len(fechas)):
            if (fechas[i] - fechas[i - 1]).days != 1:
                raise ValueError("calendario no continuo ASC")
        object.__setattr__(self, "_fechas", tuple(fechas))

    @property
    def fechas(self) -> tuple:
        """Los días como datetime.date (parseados una vez en __post_init__)."""
        return self._fechas

    def como_pares(self) -> list:
        """Vista [(date, float|None)] para los helpers de bajo nivel."""
        return list(zip(self._fechas, self.valores))


def serie_dia(serie: list, dia: date):
    """Valor del día en la serie: float, None (hueco explícito) o AUSENTE
    (día no presente). La capa de datos la usa para montar series (D-T5-1)."""
    for d, x in serie:
        if d == dia:
            return x
        if d > dia:
            break
    return AUSENTE


def baseline_dow(s: SerieDiaria, i: int) -> Baseline:
    """Baseline rodante i−28…i−1 del weekday de dias[i] (D-T5-5; contrato §3).

    1. Posiciones j con i−28 ≤ j ≤ i−1, weekday(dias[j])==weekday(dias[i]),
       valor no-None.  2. n<4 → ciego.  3. MAD==0 → ciego conservando la
       mediana para el informe (vector (ñ)).
    La posición del propio día i NUNCA entra (anti look-ahead, T-B5-7).
    ValueError: i fuera de rango o índice no entero (D-T5-4).
    """
    if not isinstance(s, SerieDiaria):
        raise ValueError("baseline_dow espera una SerieDiaria")
    if not isinstance(i, int) or not (0 <= i < len(s.valores)):
        raise ValueError("índice i fuera de rango")
    fechas = s.fechas
    lim_inf = fechas[i].toordinal() - 28
    w = fechas[i].weekday()
    vals = [s.valores[j] for j in range(max(0, i - 28), i)
            if lim_inf <= fechas[j].toordinal()  # siempre cierto con 57 cont.
            and fechas[j].weekday() == w and s.valores[j] is not None]
    n = len(vals)
    if n < 4:
        return Baseline(None, None, n, ciego=True)
    m = mediana(vals)
    M = mad(vals)
    if M == 0.0:
        return Baseline(_dec4(m), None, n, ciego=True)
    return Baseline(_dec4(m), _dec4(M), n, ciego=False)


def z_r(x: float, base: Baseline) -> "Decimal | None":
    """0,6745·(x − mediana)/MAD, 4 dec. HALF_UP. None si día ciego (D-T5-4).
    Simétrico: los valores negativos son válidos (tensión ↓, spec §9)."""
    if base.ciego:
        return None
    return _dec4(K_ZR * (x - float(base.mediana)) / float(base.mad))


# Alias de contrato (§3 del plan de datos, "manda esta tabla"): la función es
# la misma; el plan de Turing la llamaba z_r. Divergencia nominal documentada.
z_robusto = z_r


def u_t(x: float, base: Baseline) -> "float | None":
    """(x − mediana)/(1,4826·MAD) en FLOAT SIN CUANTIZAR: es intermedio de
    CUSUM; cuantizarlo movería los S congelados (trampa T-B5-2).
    None si día ciego (el día se salta en la recursión, D-T5-6)."""
    if base.ciego:
        return None
    return (x - float(base.mediana)) / (K_SIGMA * float(base.mad))


def elegible(docs_por_dia: list) -> bool:
    """Media de los valores no-None de los últimos 28 días ≥ 5,0 (spec §7).
    Los huecos se EXCLUYEN de la media (no cuentan como 0 — T-B5-16;
    abierta A-B5-2). Sin Decimal: devuelve bool."""
    vals = [x for x in docs_por_dia[-28:] if x is not None]
    if not vals:
        return False
    return sum(vals) / len(vals) >= 5.0


def es_dia_parcial(docs_totales_dia: int, mediana_docs_28d: Decimal) -> bool:
    """docs_totales_dia < 0,5·mediana_docs_28d, comparación ESTRICTA en float
    (A-4 cerrada; vector (j): 100 con umbral 100 NO es parcial — T-B5-11).
    La mediana se computa sobre TODOS los días previos con stats, incluidos
    parciales (sin exclusión circular). El día parcial no se evalúa pero SÍ
    entra en baselines futuras."""
    return float(docs_totales_dia) < 0.5 * float(mediana_docs_28d)

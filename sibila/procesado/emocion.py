"""Emoción por documento y agregado diario (spec §6.6).

Lexicones (NUNCA vendorizados; descarga en instalación, spec §3):
- NRC-VAD EN v2 (rango [−1,1] ya en el fichero)
- NRC-VAD ES v1 (rango [0,1]; reescalado v'=2v−1 TANTO para V como para A)
- NRC Emotion Lexicon (8 emociones binarias ES/EN)
- VADER (solo EN, `compound`; import perezoso, ausencia → degradación)

Formato de ficheros (CONGELADO, también para los fixtures de test):
- VAD: líneas "palabra<TAB>valence<TAB>arousal[<TAB>...]" UTF-8; se ignoran
  líneas cuyos campos 2º/3º no sean numéricos (cabecera).
- Emoción: líneas "palabra<TAB>emocion<TAB>0|1" UTF-8 (formato NRC clásico);
  solo cuentan las 8 emociones del orden fijo ORDEN_EMOCIONES.

Ficheros ausentes → None (degradado con aviso de la capa de datos); presentes
y corruptos → SibilaError. SHA-256 de los ficheros reales fijado en
SHA256_ESPERADOS y verificado al cargar (spec §3); los fixtures de test se
cargan con verificar_sha=False.

VADER ausente con léxicos presentes (rev. Hamilton M1 / Dijkstra M3): vector()
devuelve None para lang='en' (jamás V=(V_NRC+0)/2, sesgo silencioso); ES no
usa VADER y no cambia. Se avisa UNA vez por carga en cargar_lexicos; la capa
de datos ya lo cuenta en procesa.sin_emocion.
"""
import hashlib
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from .. import SibilaError
from .dedup import _content_words

log = logging.getLogger("sibila.procesado.emocion")

_C4 = Decimal("0.0001")

# Orden NRC fijo de las 8 emociones (contrato de EmoDoc.emociones).
ORDEN_EMOCIONES = ("anger", "anticipation", "disgust", "fear",
                   "joy", "sadness", "surprise", "trust")

_COBERTURA_MIN = 0.30   # spec §6.6
_MIN_CASADAS = 3

# SHA-256 de los ficheros reales (fijados en T2/Hopper, cierra R1-Hamilton de
# B4/D-040): computados sobre los artefactos NORMALIZADOS que consume el
# programa (tools/descargar_recursos.py), recomputados por doble descarga
# (D-030). Clave = nombre de fichero; los fixtures de test usan
# verificar_sha=False.
SHA256_ESPERADOS: dict = {
    "nrc_emociones_en.txt": "0b1ce8ec1297f523eee882fd3973cca394c0b20ff54c3beb0dbd952efe314a81",
    "nrc_emociones_es.txt": "60124be34075390015aea04eb86574a4ae84f943f5fb5c9a196ec63a79abe46e",
    "nrc_vad_en.txt": "71518ac0e3cea299b43714190b4fc3ec55acf4302eb04b9c36d148aaffbe9d81",
    "nrc_vad_es.txt": "0ac2f639f8b222ef5bce14dac26bb6dd34217d80a447d6443c2a21fa77da75f7",
}


@dataclass(frozen=True)
class Lexicos:
    vad_en: dict            # palabra -> (v, a) en [−1,1]
    vad_es: dict            # palabra -> (v, a) ya reescalado a [−1,1]
    emo_en: dict            # palabra -> tuple[8×0/1] en ORDEN_EMOCIONES
    emo_es: dict
    vader: object           # analyzer VADER o None (solo EN, compound)


@dataclass(frozen=True)
class EmoDoc:
    v: float
    a: float                # ambos en [−1,1], 4 dec HALF_UP
    emociones: tuple        # 8 binarias en ORDEN_EMOCIONES
    n_casadas: int
    cobertura: float        # 4 dec HALF_UP


def _q4(x: float) -> float:
    return float(Decimal(str(x)).quantize(_C4, ROUND_HALF_UP))


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _cargar_vad(ruta: Path, *, reescalar: bool) -> dict:
    d = {}
    with ruta.open(encoding="utf-8") as f:
        for i, linea in enumerate(f, 1):
            campos = linea.rstrip("\n").split("\t")
            if len(campos) < 3:
                if linea.strip():
                    raise SibilaError(f"{ruta.name}:{i}: línea VAD mal formada")
                continue
            try:
                v, a = float(campos[1]), float(campos[2])
            except ValueError:
                if i == 1:
                    continue  # cabecera
                raise SibilaError(f"{ruta.name}:{i}: valores VAD no numéricos") from None
            if reescalar:
                v, a = 2 * v - 1, 2 * a - 1
            d[campos[0]] = (v, a)
    return d


def _cargar_emociones(ruta: Path) -> dict:
    d = {}
    with ruta.open(encoding="utf-8") as f:
        for i, linea in enumerate(f, 1):
            campos = linea.rstrip("\n").split("\t")
            if len(campos) != 3:
                if linea.strip():
                    raise SibilaError(f"{ruta.name}:{i}: línea de emoción mal formada")
                continue
            palabra, emo, bit = campos
            if emo not in ORDEN_EMOCIONES or bit not in ("0", "1"):
                raise SibilaError(f"{ruta.name}:{i}: emoción o bit desconocido")
            if bit == "1":
                vec = list(d.get(palabra, (0,) * 8))
                vec[ORDEN_EMOCIONES.index(emo)] = 1
                d[palabra] = tuple(vec)
    return d


def _cargar_vader():
    try:
        import importlib
        mod = importlib.import_module("vaderSentiment.vaderSentiment")
    except ImportError:
        return None  # dep ausente: degradación (EN perderá su componente VADER)
    return mod.SentimentIntensityAnalyzer()


def cargar_lexicos(cfg_recursos, *, verificar_sha: bool = True) -> "Lexicos | None":
    """cfg_recursos: mapping/objeto con rutas `nrc_vad_en`, `nrc_vad_es`,
    `nrc_emociones_en`, `nrc_emociones_es`. Alguno ausente → None (modo
    degradado). Presente pero ilegible/corrupto o SHA-256 distinto →
    SibilaError. UTF-8 explícito (trampa T-11)."""
    def _ruta(nombre):
        if isinstance(cfg_recursos, dict):
            return cfg_recursos.get(nombre)
        return getattr(cfg_recursos, nombre, None)

    rutas = {n: _ruta(n) for n in
             ("nrc_vad_en", "nrc_vad_es", "nrc_emociones_en", "nrc_emociones_es")}
    if any(r is None or not Path(r).is_file() for r in rutas.values()):
        return None
    rutas = {n: Path(r) for n, r in rutas.items()}
    if verificar_sha:
        for r in rutas.values():
            esperado = SHA256_ESPERADOS.get(r.name)
            if esperado is not None and _sha256(r) != esperado:
                raise SibilaError(f"SHA-256 no coincide: {r.name}")
    try:
        vad_en = _cargar_vad(rutas["nrc_vad_en"], reescalar=False)
        vad_es = _cargar_vad(rutas["nrc_vad_es"], reescalar=True)
        emo_en = _cargar_emociones(rutas["nrc_emociones_en"])
        emo_es = _cargar_emociones(rutas["nrc_emociones_es"])
    except OSError as e:
        raise SibilaError(f"léxico ilegible: {e}") from e
    vader = _cargar_vader()
    if vader is None:
        # Aviso UNA vez por carga (rev. Hamilton M1): EN queda sin emoción
        # (vector()=None); la capa lo cuenta en procesa.sin_emocion.
        log.warning("VADER no importable: emoción EN desactivada "
                    "(modo degradado; ES no afectada)")
    return Lexicos(vad_en=vad_en, vad_es=vad_es, emo_en=emo_en, emo_es=emo_es,
                   vader=vader)


def vector(lex: "Lexicos | None", texto_limpio: str, lang: "str | None") -> "EmoDoc | None":
    """None si: lex ausente, lang ∉ {es,en}, lang='en' sin VADER disponible
    (rev. Hamilton M1 / Dijkstra M3: nunca (V_NRC+0)/2 silencioso), <3 content
    words casadas, o cobertura = casadas/n_content_words < 0,30 (spec §6.6)."""
    if lex is None or lang not in ("es", "en"):
        return None
    if lang == "en" and lex.vader is None:
        return None
    vad = lex.vad_es if lang == "es" else lex.vad_en
    emo = lex.emo_es if lang == "es" else lex.emo_en
    cw = _content_words(texto_limpio, lang)
    if not cw:
        return None
    casadas = [w for w in cw if w in vad]
    n_casadas = len(casadas)
    cobertura = n_casadas / len(cw)
    if n_casadas < _MIN_CASADAS or cobertura < _COBERTURA_MIN:
        return None
    v_nrc = sum(vad[w][0] for w in casadas) / n_casadas
    a = sum(vad[w][1] for w in casadas) / n_casadas
    if lang == "en":
        compound = 0.0
        if lex.vader is not None:
            compound = float(lex.vader.polarity_scores(texto_limpio)["compound"])
        v = (v_nrc + compound) / 2
    else:
        v = v_nrc
    emociones = [0] * 8
    for w in casadas:
        bits = emo.get(w)
        if bits:
            for k in range(8):
                emociones[k] |= bits[k]
    return EmoDoc(v=_q4(v), a=_q4(a), emociones=tuple(emociones),
                  n_casadas=n_casadas, cobertura=_q4(cobertura))


def agregar_dia(items: list) -> "tuple[float, float, int, float] | None":
    """items = (EmoDoc, w) con w ya compuesto por la capa de datos.
    (V_media_ponderada, A_media_ponderada, n, n_efectivo=(Σw)²/Σw²);
    None si lista vacía o Σw² = 0 (n/d jamás 0 — trampa T-8)."""
    if not items:
        return None
    sw = sum(w for _, w in items)
    sw2 = sum(w * w for _, w in items)
    if sw2 == 0:
        return None
    v = sum(e.v * w for e, w in items) / sw
    a = sum(e.a * w for e, w in items) / sw
    return _q4(v), _q4(a), len(items), _q4(sw * sw / sw2)

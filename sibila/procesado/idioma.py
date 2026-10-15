"""Detección de idioma (spec §6.3): fastText (lid.176.ftz) con fallback a
lingua. Dependencias de importación PEREZOSA (dentro de cargar/detectar): el
módulo se importa sin ellas y degrada a None.

Umbrales fijados (provisional Fase 1): fastText ≥0,80; si dudoso → lingua
≥0,80 sobre el conjunto congelado {ES, EN, PT, FR, DE, IT, CA, EU} (8;
lingua 2.2.0 no soporta GL);
si no → (None, 0.0).
"""
from pathlib import Path

from .. import SibilaError

UMBRAL = 0.80
_MAX_PALABRAS = 200


def cargar_detector(ruta_modelo) -> "object | None":
    """Carga lid.176.ftz vía fasttext-predict. Fichero ausente → None (modo
    degradado). Presente pero ilegible/corrupto → SibilaError (fallo visible).
    La ruta se pasa como str absoluta (humo bajo rutas con acentos, T-11)."""
    if ruta_modelo is None:
        return None
    ruta = Path(ruta_modelo)
    if not ruta.is_file():
        return None
    try:
        import importlib
        ft = importlib.import_module("fasttext")  # fasttext-predict, perezoso
    except ImportError:  # dep ausente: degradación, nunca rompe la batería
        return None
    try:
        return ft.FastText.load_model(str(ruta))
    except Exception as e:
        raise SibilaError(f"modelo de idioma ilegible o corrupto: {ruta}") from e


_LINGUA_CACHE = None   # detector lingua, construcción perezosa UNA vez (rev.
                       # Hamilton M4: build() carga 8 modelos; no por llamada)


def _construir_lingua():
    """Detector lingua sobre el conjunto congelado (determinismo y coste).
    Caché a nivel de módulo: se construye como mucho una vez por proceso.
    Lanza ImportError si lingua no está instalada.
    Conjunto de 8: el gallego (GL) NO existe en lingua 2.2.0 (IsoCode639_1
    no lo soporta) — detectado al ejercitar el fallback por primera vez con
    lingua instalada; antes el AttributeError quedaba enmascarado por la
    ausencia de la dependencia (ver D-066)."""
    global _LINGUA_CACHE
    if _LINGUA_CACHE is None:
        import importlib
        lingua = importlib.import_module("lingua")
        _LINGUA_CACHE = lingua.LanguageDetectorBuilder.from_iso_codes_639_1(
            lingua.IsoCode639_1.ES, lingua.IsoCode639_1.EN, lingua.IsoCode639_1.PT,
            lingua.IsoCode639_1.FR, lingua.IsoCode639_1.DE, lingua.IsoCode639_1.IT,
            lingua.IsoCode639_1.CA, lingua.IsoCode639_1.EU,
        ).build()
    return _LINGUA_CACHE


def _detectar_lingua(texto: str):
    """(lang, conf) con lingua, o None si no está importable o no supera el
    umbral."""
    try:
        det = _construir_lingua()
    except ImportError:
        return None
    confs = det.compute_language_confidence_values(texto)
    if not confs:
        return None
    mejor = max(confs, key=lambda c: c.value)
    if mejor.value >= UMBRAL:
        return mejor.language.iso_code_639_1.name.lower(), float(mejor.value)
    return None


def detectar(det, texto_limpio: str) -> "tuple[str | None, float]":
    """(lang ISO-639-1 minúsculas, confianza). (None, 0.0) si sin idioma fiable,
    detector ausente, o texto de <3 palabras (fastText ahí es ruido).
    Devuelve el idioma aunque no sea es/en: excluir del corpus es decisión de
    la capa de datos."""
    if det is None:
        return None, 0.0
    palabras = texto_limpio.split()
    if len(palabras) < 3:
        return None, 0.0
    texto = " ".join(palabras[:_MAX_PALABRAS])
    etiquetas, confs = det.predict(texto, k=1)
    if not etiquetas:
        return None, 0.0
    lang = etiquetas[0].replace("__label__", "").lower()
    conf = float(confs[0])
    if conf >= UMBRAL:
        return lang, conf
    if conf > 0.0:
        r = _detectar_lingua(texto)
        if r is not None:
            return r
    return None, 0.0

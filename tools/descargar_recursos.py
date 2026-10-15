#!/usr/bin/env python3
"""Descarga y verifica los recursos de datos del paquete (T2, D-048):
lid.176.ftz (fastText) + 4 léxicos NRC normalizados al formato tabulado que
espera procesa (palabra⇥v⇥a / palabra⇥emoción⇥bit, UTF-8, \n).

- data_dir vía sibila.config.load_config() — NUNCA hardcodeado (D-048/H3);
  crea <data_dir>/recursos (mkdir -p) porque corre ANTES de init.
- SHA-256 fijado: lid.176.ftz contra SHA256_LID176 (abajo); NRC contra
  SHA256_ESPERADOS importado de sibila.procesado.emocion (ÚNICA fuente de
  verdad). Dict vacío → FALLO explícito "hashes no fijados" (nunca se
  descarga sin verificar, R1-Hamilton).
- Idempotente: presente con hash correcto → "[OK] ya presente", no
  re-descarga. Presente con hash malo → FALLO, NUNCA pisa en silencio.
- Fallo de red → [AVISO] claro y exit 0 (degradado documentado: procesa
  degrada a sin-idioma/sin-emoción, A5); hash malo → exit 1.

Licencias (referencia, D-039/H3): NRC-VAD v2.1 y NRC Emotion Lexicon v0.92
© National Research Council Canada — uso libre no comercial (investigación/
educación); NO se redistribuyen (por eso se descargan en instalación).
http://saifmohammad.com/WebPages/nrc-vad.html · .../NRC-EmotionLexicon.htm
lid.176.ftz © Facebook AI Research (fastText, licencia MIT).
"""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo raíz

URL_LID176 = ("https://dl.fbaipublicfiles.com/fasttext/supervised-models/"
              "lid.176.ftz")
SHA256_LID176 = "8f3472cfe8738a7b6099e8e999c3cbfae0dcd15696aac7d7738a8039db603e83"
# verificado por doble descarga del URL oficial (938013 bytes, D-030)

URL_VAD_V2 = ("https://saifmohammad.com/WebDocs/Lexicons/"
              "NRC-VAD-Lexicon-v2.1.zip")
URL_VAD_V1 = ("https://saifmohammad.com/WebDocs/Lexicons/"
              "NRC-VAD-Lexicon.zip")
URL_EMO = ("https://saifmohammad.com/WebDocs/Lexicons/"
           "NRC-Emotion-Lexicon.zip")

_EMO_V2_UNIGRAMS = "NRC-VAD-Lexicon-v2.1/Unigrams/unigrams-NRC-VAD-Lexicon-v2.1.txt"
_ORDEN_EMO = ("anger", "anticipation", "disgust", "fear",
              "joy", "sadness", "surprise", "trust")


class RedError(Exception):
    """Fallo de red: degradado documentado, NO aborta la instalación."""


# Cabeceras de navegador: el servidor de saifmohammad.com rechaza con
# HTTP 406 el User-Agent por defecto de python-requests (verificado en
# desarrollo, 2026-10-15: 406 con UA requests, 200 con UA navegador).
_CABECERAS_HTTP = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "application/zip,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
}


def _descargar(url: str, *, timeout: int = 600) -> bytes:
    """Descarga real (requests pinneado). Inyectable en tests (T-INS-4)."""
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers=_CABECERAS_HTTP)
        r.raise_for_status()
        return r.content
    except Exception as e:
        raise RedError(f"{url}: {e}") from e


# --- Normalizadores (compartidos con tools/generar_sha_recursos.py) ---------

def normalizar_vad_en(zip_bytes: bytes) -> bytes:
    """VAD v2.1 EN: unigrams term⇥valence⇥arousal⇥dominance ya en [-1,1]
    (el loader consume los 3 primeros campos sin reescalar). Se conserva el
    fichero oficial tal cual (menos transformación = menos riesgo)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return z.read(_EMO_V2_UNIGRAMS)


def normalizar_vad_es(zip_bytes: bytes) -> bytes:
    """VAD v1 ES: OneFilePerLanguage/Spanish-NRC-VAD-Lexicon.txt tiene formato
    English⇥Valence⇥Arousal⇥Dominance⇥Spanish (scores en [0,1]; el loader los
    reescala a [-1,1]). Se transpone a palabra_es⇥v⇥a (el formato del loader)
    y se conserva la cabecera term⇥valence⇥arousal (el loader la salta)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        crudo = z.read("NRC-VAD-Lexicon/OneFilePerLanguage/"
                       "Spanish-NRC-VAD-Lexicon.txt").decode("utf-8")
    out = ["term\tvalence\tarousal"]
    for lin in crudo.split("\n")[1:]:
        campos = lin.rstrip("\r").split("\t")
        if len(campos) >= 5 and campos[4].strip():
            out.append(f"{campos[4]}\t{campos[1]}\t{campos[2]}")
    return ("\n".join(out) + "\n").encode("utf-8")


def normalizar_emo_en(zip_bytes: bytes) -> bytes:
    """NRC Emotion Lexicon EN (wordlevel v0.92): term⇥emoción⇥bit. Se eliminan
    las filas positive/negative (no son emociones del ORDEN fijo y el loader
    las rechazaría); el resto se conserva tal cual."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        crudo = z.read("NRC-Emotion-Lexicon/NRC-Emotion-Lexicon-Wordlevel-v0.92.txt")
    lineas = []
    for lin in crudo.decode("utf-8").split("\n"):
        campos = lin.split("\t")
        if len(campos) == 3 and campos[1] in _ORDEN_EMO:
            lineas.append(lin)
    return ("\n".join(lineas) + "\n").encode("utf-8")


def normalizar_emo_es(zip_bytes: bytes) -> bytes:
    """NRC Emotion Lexicon ES: fichero OneFilePerLanguage/Spanish-NRC-EmoLex.txt
    (formato ancho: English⇥8 emociones⇥negative⇥positive⇥Spanish). Se
    transpone a palabra_es⇥emoción_en⇥1 (solo bits 1; etiquetas en INGLÉS,
    que es lo que espera el loader)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        crudo = z.read("NRC-Emotion-Lexicon/OneFilePerLanguage/"
                       "Spanish-NRC-EmoLex.txt").decode("utf-8")
    lineas = crudo.split("\n")
    cab = [c.strip().lower() for c in lineas[0].split("\t")]
    i_es = cab.index("spanish word")
    idx_emo = [(cab.index(e), e) for e in _ORDEN_EMO]
    out = []
    for lin in lineas[1:]:
        campos = lin.rstrip("\r").split("\t")
        if len(campos) <= i_es or not campos[i_es].strip():
            continue
        for col, emo in idx_emo:
            if campos[col] == "1":
                out.append(f"{campos[i_es]}\t{emo}\t1")
    return ("\n".join(out) + "\n").encode("utf-8")


# nombre destino → (url, normalizador, clave en SHA256_ESPERADOS o None)
ESPEC = {
    "lid.176.ftz": (URL_LID176, lambda b: b, None),
    "nrc_vad_en.txt": (URL_VAD_V2, normalizar_vad_en, "nrc_vad_en.txt"),
    "nrc_vad_es.txt": (URL_VAD_V1, normalizar_vad_es, "nrc_vad_es.txt"),
    "nrc_emociones_en.txt": (URL_EMO, normalizar_emo_en, "nrc_emociones_en.txt"),
    "nrc_emociones_es.txt": (URL_EMO, normalizar_emo_es, "nrc_emociones_es.txt"),
}


def _sha256(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


def descargar(recursos_dir: Path, *, bajador=None, imprimir=print) -> int:
    """Descarga/verifica todos los recursos en `recursos_dir`.
    Exit: 0 si todo verificado o fallo de RED (degradado documentado);
    1 si hash incorrecto (dict vacío incluido). Idempotente."""
    from sibila.procesado import emocion
    bajador = bajador or _descargar
    esperados = dict(emocion.SHA256_ESPERADOS)
    esperados["lid.176.ftz"] = SHA256_LID176
    if not emocion.SHA256_ESPERADOS:
        imprimir("[FALLO] hashes no fijados: instalación no verificable "
                 "(SHA256_ESPERADOS vacío en procesado/emocion.py)")
        return 1
    recursos_dir.mkdir(parents=True, exist_ok=True)   # corre ANTES de init
    zips: dict = {}          # caché url → bytes (los 4 NRC salen de 3 zips)
    roto = False
    for nombre, (url, normaliza, _clave) in ESPEC.items():
        destino = recursos_dir / nombre
        esperado = esperados[nombre]
        if destino.is_file():
            actual = _sha256(destino.read_bytes())
            if actual == esperado:
                imprimir(f"[OK] ya presente: {nombre}")
                continue
            imprimir(f"[FALLO] {nombre} presente con hash INCORRECTO "
                     f"(no se pisa; borra el fichero y reintenta)")
            roto = True
            continue
        try:
            if url not in zips:
                zips[url] = bajador(url)
            datos = normaliza(zips[url])
        except RedError as e:
            imprimir(f"[AVISO] sin red para {nombre} ({e}). Recursos "
                     "descargables aparte: corre tools\\descargar_recursos.py; "
                     "procesa degradará a sin-idioma/sin-emoción hasta "
                     "entonces (modo degradado documentado).")
            continue
        except (ValueError, KeyError, zipfile.BadZipFile) as e:
            imprimir(f"[FALLO] {nombre}: descarga ilegible ({e})")
            roto = True
            continue
        if _sha256(datos) != esperado:
            imprimir(f"[FALLO] {nombre}: SHA-256 de la descarga NO coincide "
                     f"(esperado {esperado[:12]}…); no se escribe nada")
            roto = True
            continue
        destino.write_bytes(datos)
        imprimir(f"[OK] descargado y verificado: {nombre}")
    return 1 if roto else 0


def main(argv) -> int:
    from sibila import config
    try:
        cfg = config.load_config()
    except Exception as e:
        print(f"[FALLO] configuración: {e}")
        return 1
    return descargar(cfg.data_dir / "recursos")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

#!/usr/bin/env python3
"""SOLO DESARROLLO (con red): genera los SHA-256 reales de los léxicos NRC
normalizados y los imprime listos para pegar en
sibila/procesado/emocion.py::SHA256_ESPERADOS (cierra R1-Hamilton de B4).

Flujo: descarga las fuentes OFICIALES → normaliza con las MISMAS funciones
de tools/descargar_recursos.py (única fuente de verdad del formato) → escribe
en <data_dir>/recursos/ → computa SHA-256 del fichero FINAL escrito → verifica
recargando con cargar_lexicos(verificar_sha=True) → imprime el dict Python.

La doble computación del mismo script NO cuenta como verificación (D-030):
la revisión recomputa con sha256sum / Get-FileHash sobre los ficheros.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo raíz
sys.path.insert(0, str(Path(__file__).resolve().parent))         # tools/

import descargar_recursos as dr  # noqa: E402


def main(argv) -> int:
    from sibila import config
    from sibila.procesado import emocion
    cfg = config.load_config()
    destino = cfg.data_dir / "recursos"
    destino.mkdir(parents=True, exist_ok=True)
    zips = {}
    hashes = {}
    for nombre, (url, normaliza, clave) in dr.ESPEC.items():
        if clave is None:
            continue                     # lid.176.ftz: su SHA va en el otro script
        if url not in zips:
            print(f"descargando {url} …")
            zips[url] = dr._descargar(url)
        datos = normaliza(zips[url])
        (destino / nombre).write_bytes(datos)
        hashes[nombre] = dr._sha256(datos)
        print(f"  {nombre}: {len(datos)} bytes, sha256 {hashes[nombre]}")
    # verificación: recargar con verificación activada contra el dict generado
    emocion.SHA256_ESPERADOS.update(hashes)
    lex = emocion.cargar_lexicos(
        {k: destino / f"{k}.txt" for k in
         ("nrc_vad_en", "nrc_vad_es", "nrc_emociones_en", "nrc_emociones_es")},
        verificar_sha=True)
    assert lex is not None
    print("\n# Pegar en sibila/procesado/emocion.py (línea SHA256_ESPERADOS):")
    print("SHA256_ESPERADOS: dict = {")
    for nombre in sorted(hashes):
        print(f'    "{nombre}": "{hashes[nombre]}",')
    print("}")
    print(f"\n# SHA256_LID176 para tools/descargar_recursos.py: "
          f"computar sobre el fichero descargado de {dr.URL_LID176}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

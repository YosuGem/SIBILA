#!/usr/bin/env python3
"""Genera config.local.toml con una hmac_key nueva SOLO si no existe
(idempotente: NUNCA pisa la clave — T-INS-3). Factorizado del snippet
python -c de instalar.bat para ser testeable (plan T2 §4).

Uso: python tools/generar_secretos.py [ruta_config_local.toml]
Exit 0 siempre que pudo escribir/verificar; 1 en error de E/S.
Imprime [OK] generado / [OK] ya existe.
"""
import secrets
import sys
from pathlib import Path


def generar_secretos(ruta: Path) -> bool:
    """Crea `ruta` con [secretos] hmac_key (64 hex) si no existe.
    Devuelve True si el fichero queda listo (creado o ya presente con clave),
    False si existía pero SIN hmac_key (no se toca: avisar al operador)."""
    if ruta.exists():
        texto = ruta.read_text(encoding="utf-8")
        return "hmac_key" in texto
    clave = secrets.token_hex(32)
    ruta.write_text(f'[secretos]\nhmac_key = "{clave}"\n', encoding="ascii")
    return True


def main(argv) -> int:
    ruta = Path(argv[1]) if len(argv) > 1 else Path("config.local.toml")
    try:
        existia = ruta.exists()
        ok = generar_secretos(ruta)
    except OSError as e:
        print(f"[FALLO] no se pudo generar {ruta}: {e}")
        return 1
    if not ok:
        print(f"[FALLO] {ruta} existe pero no tiene hmac_key: "
              "no se pisa; añade la clave a mano")
        return 1
    print(f"[OK] {ruta} " + ("ya existe: no se toca" if existia
                             else "generado con hmac_key nueva (nunca sale de este PC)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

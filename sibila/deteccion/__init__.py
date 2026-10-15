"""sibila.deteccion — algoritmos PUROS de detección temporal (spec §7).

Sin BD, sin reloj, sin red, sin ficheros; deterministas (cero RNG, cero
`date.today()`/`datetime.now()`: el día evaluado siempre entra como parámetro
— guardián T-B5-13 en tests/test_deteccion_guardian.py). Stdlib puro.

Política de decimales (D-T5-3): cálculo interno en float IEEE-754 SIN
redondear intermedios; toda salida REAL pública se devuelve como Decimal
cuantizado a 4 decimales ROUND_HALF_UP SOLO al final.
"""

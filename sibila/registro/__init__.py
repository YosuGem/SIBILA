"""sibila.registro — funciones PURAS del registro sellado de predicciones
(spec §8, plan Bloque 6 Turing, D-043).

Sin sqlite3, sin disco, sin reloj (prohibido now()/today(): `created_at`
entra siempre como parámetro — T-B6-13), sin subprocess, sin red.
Deterministas. Guardián AST en tests/test_registro_guardian.py.
"""

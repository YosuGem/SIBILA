"""sibila — núcleo del programa de lingüística predictiva (spec §1).

Sin efectos laterales al importar: importar este paquete no toca disco ni red
(trampa T11). Sin __version__: las versiones del programa las asigna solo Yosu
(D-019); el schema interno se versiona con PRAGMA user_version (D-B1-01).
"""


class SibilaError(Exception):
    """Base de los errores previstos del programa (mensajes en español)."""


__all__ = ["SibilaError"]

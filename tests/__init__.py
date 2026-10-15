# Batería T1 del núcleo sibila (unittest stdlib; discovery)
#
# Entorno sandbox: $HOME es efímero entre sesiones (pip --user se pierde) y el repo
# vive en almacenamiento persistente. Las dependencias del bloque 2 se instalan por
# tanto en <repo>/../deps (pip --target), que SÍ persiste. En Hermes no hace falta:
# las deps llegan por requirements.txt y este bloque es un no-op si ../deps no existe.
import sys as _sys
from pathlib import Path as _Path

_deps = _Path(__file__).resolve().parent.parent.parent / "deps"
if _deps.is_dir() and str(_deps) not in _sys.path:
    _sys.path.insert(0, str(_deps))

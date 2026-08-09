"""Version del proyecto, leida de pyproject.toml.

`pyproject.toml` es la fuente unica: mantener el numero tambien hardcodeado en
el codigo garantiza que tarde o temprano diverjan y que /docs anuncie una
version que no es la desplegada.

No se usa ``importlib.metadata`` porque el proyecto se ejecuta desde el
checkout (``pythonpath = ["."]``), sin instalarse como paquete, asi que no hay
metadata de distribucion que consultar.
"""

import logging
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

# Si el archivo no esta (p. ej. un deploy que solo copia src/), el API igual
# tiene que arrancar: la version es informativa, no critica.
_FALLBACK = "0.0.0+desconocida"


def get_version() -> str:
    """Lee la version declarada en pyproject.toml.

    Returns:
        La version del proyecto, o ``_FALLBACK`` si el archivo no se puede
        leer o no declara ``project.version``.
    """
    try:
        with _PYPROJECT.open("rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        logger.warning(
            "No se pudo leer la version de %s; se usa %s.", _PYPROJECT, _FALLBACK
        )
        return _FALLBACK

"""Configuracion de acceso a PostgreSQL compartida por el ETL y el API.

Aqui vive **solo** lo que las dos capas tienen realmente en comun: de donde sale
la connection string y que search_path fija cada conexion. La forma de conectar
NO se comparte a proposito, porque los ciclos de vida son distintos:

- El **ETL** (``src.etl.load``) es un batch que corre una vez y termina: abre
  una conexion directa y la cierra. Un pool ahi seria overhead sin beneficio.
- El **API** (``src.api.database``) es un proceso largo que atiende requests
  concurrentes: usa un pool perezoso que se reutiliza entre peticiones.

Unificarlas detras de una sola abstraccion obligaria a la peor de las dos: o el
batch carga un pool que no usa, o el API abre y cierra una conexion por request.
"""

import os

# El proyecto vive en el esquema dedicado `fx`. Fijar el search_path evita
# calificar el esquema en cada query, aunque el DML critico igual lo califica.
SEARCH_PATH_SQL = "SET search_path TO fx, public;"


def get_database_url() -> str:
    """Lee la connection string de PostgreSQL desde el entorno.

    Nunca se hardcodea: en local viene del ``.env`` y en CI/prod de las
    variables del entorno.

    Returns:
        La connection string.

    Raises:
        KeyError: Si ``DATABASE_URL`` no esta definida.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise KeyError(
            "DATABASE_URL no esta definida. Copia .env.example a .env "
            "y rellena la connection string."
        )
    return db_url

import logging


def configure_logging(level: str) -> None:
    """
    Configure the process-wide baseline logger.

    Later batches will introduce structured request/security logging. This
    foundation deliberately avoids logging request bodies or credentials.
    """
    normalized_level = level.upper()

    numeric_level = getattr(logging, normalized_level, None)

    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    logging.basicConfig(
        level=numeric_level,
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(name)s "
            "%(message)s"
        ),
    )
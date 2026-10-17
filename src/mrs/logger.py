import logging
import sys

LOGGER_NAME = "mrs"
LEVEL_MARKERS = {
    logging.DEBUG: "[#]",
    logging.INFO: "[#]",
    logging.WARNING: "[!]",
    logging.ERROR: "[X]",
}

logger = logging.getLogger(LOGGER_NAME)


class _MarkerFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        marker = LEVEL_MARKERS.get(record.levelno, "[#]")
        formatted = f"{marker} {record.getMessage()}"
        return formatted


def configure_logging(verbose: bool = False):
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_MarkerFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

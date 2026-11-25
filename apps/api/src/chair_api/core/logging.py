"""Structured JSON logging and request correlation setup."""

import logging
import sys


def configure_logging(debug: bool = False) -> None:
    """Configure root logger for structured service output."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )

from __future__ import annotations

import logging
from pathlib import Path


def setup_logger(
    name: str = "qradar_refset",
    *,
    level: str = "INFO",
    log_file: str | None = None,
) -> logging.Logger:
    """
    Configure console logging and optional file logging.

    Levels:
        DEBUG, INFO, WARNING, ERROR, CRITICAL
    """
    logger = logging.getLogger(name)

    numeric_level = getattr(
        logging,
        level.upper(),
        logging.INFO,
    )

    logger.setLevel(numeric_level)
    logger.propagate = False

    # Avoid duplicate handlers when CLI imports/reuses logger.
    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(numeric_level)
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_file:
        log_path = Path(log_file).expanduser().resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(
            log_path,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

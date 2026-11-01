import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from core.config import BASE_DIR, settings

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "football_intelligence.log"


def get_logger(agent_name: str) -> logging.Logger:
    """
    Devuelve un logger configurado para el agente o modulo especificado.
    Escribe tanto en consola como en un archivo rotativo local.
    """
    logger = logging.getLogger(agent_name)

    if logger.handlers:
        return logger

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | [%(name)s] | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Salida a archivo con rotacion (max 5 MB por archivo, guarda 3 copias)
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 2. Salida a consola en Windows (UTF-8 seguro)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

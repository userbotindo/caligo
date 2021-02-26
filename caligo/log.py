import logging
import os
from datetime import datetime

import colorlog


def setup_log() -> None:
    """Configures logging"""
    cache_path = os.environ.get("HOME") + "/" + ".cache/caligo"
    if not os.path.exists(cache_path):
        os.makedirs(cache_path)

    level = logging.INFO

    logging.root.setLevel(level)

    logfile_format = "[ %(asctime)s : %(levelname)-7s ] %(name)-7s | %(message)s"
    logfile_name = f"caligo-{datetime.now().strftime('%Y-%m-%d')}.log"
    logfile = logging.FileHandler(f"{cache_path}/{logfile_name}")
    formatter = logging.Formatter(logfile_format, datefmt="%H:%M:%S")
    logfile.setFormatter(formatter)
    logfile.setLevel(level)

    stderr_format = (
        "  %(log_color)s%(levelname)-7s%(reset)s  |  %(name)-7s  |  "
        "%(log_color)s%(message)s%(reset)s")
    stream = logging.StreamHandler()
    formatter = colorlog.ColoredFormatter(stderr_format)
    stream.setLevel(level)
    stream.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(logfile)
    root.addHandler(stream)

    logging.getLogger("pyrogram").setLevel(logging.WARNING)

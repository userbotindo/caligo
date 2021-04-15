import logging
import os
from datetime import datetime
from pathlib import Path

import colorlog

level = logging.INFO


def setup_log() -> None:
    """Configures logging"""
    path = Path.home() / ".cache" / "caligo"
    path.mkdir(parents=True, exist_ok=True)
    # Check if running on container
    container = bool(os.environ.get("CONTAINER") == "True")

    logging.root.setLevel(level)

    logfile_name = f"caligo-{datetime.now().strftime('%Y-%m-%d')}.log"
    logfile = logging.FileHandler(f"{str(path)}/{logfile_name}")
    formatter = logging.Formatter("[ %(asctime)s : %(levelname)-7s ] "
                                  "%(name)-11s | %(message)s",
                                  datefmt="%H:%M:%S")
    logfile.setFormatter(formatter)
    logfile.setLevel(level)

    if container is True:
        formatter = logging.Formatter(
            "  %(levelname)-7s  |  %(name)-11s  |  %(message)s")
    else:
        formatter = colorlog.ColoredFormatter(
            "  %(log_color)s%(levelname)-7s%(reset)s  |  "
            "%(name)-11s  |  %(log_color)s%(message)s%(reset)s")
    stream = logging.StreamHandler()
    stream.setLevel(level)
    stream.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(logfile)
    root.addHandler(stream)

    logging.getLogger("pyrogram").setLevel(logging.ERROR)

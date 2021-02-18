import logging
import colorlog

from datetime import datetime


def setup_log() -> None:
    """Configures logging"""
    level = logging.INFO

    logging.root.setLevel(level)

    # Logging into file
    format = "[ %(asctime)s : %(levelname)-7s ] %(name)-7s | %(message)s"
    logfile_name = f"caligo-{datetime.now().strftime('%Y-%m-%d')}.log"
    logfile = logging.FileHandler(f"caligo/{logfile_name}")
    formatter = logging.Formatter(format, datefmt="%H:%M:%S")
    logfile.setFormatter(formatter)
    logfile.setLevel(level)

    # Logging into stdout with color
    format = ("  %(log_color)s%(levelname)s%(reset)s  |  %(name)-7s  |  "
              "%(log_color)s%(message)s%(reset)s")
    stream = logging.StreamHandler()
    formatter = colorlog.ColoredFormatter(format)
    stream.setLevel(level)
    stream.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(logfile)
    root.addHandler(stream)

    # only set level to WARNING
    logging.getLogger("pyrogram").setLevel(logging.WARNING)

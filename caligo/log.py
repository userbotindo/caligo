import logging
from datetime import datetime
from pathlib import Path


def setup_log() -> None:
    """Configures logging"""
    path = Path.home() / ".cache" / "caligo"
    path.mkdir(parents=True, exist_ok=True)

    level = logging.INFO

    logging.root.setLevel(level)

    logfile_format = "[ %(asctime)s : %(levelname)-7s ] %(name)-11s | %(message)s"
    logfile_name = f"caligo-{datetime.now().strftime('%Y-%m-%d')}.log"
    logfile = logging.FileHandler(f"{str(path)}/{logfile_name}")
    formatter = logging.Formatter(logfile_format, datefmt="%H:%M:%S")
    logfile.setFormatter(formatter)
    logfile.setLevel(level)

    stderr_format = "  %(levelname)-7s  |  %(name)-11s  |  %(message)s"
    stream = logging.StreamHandler()
    formatter = logging.Formatter(stderr_format)
    stream.setLevel(level)
    stream.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(logfile)
    root.addHandler(stream)

    logging.getLogger("pyrogram").setLevel(logging.ERROR)

import logging

import colorlog

level = logging.INFO


def setup_log(colorlog_enable: bool = False) -> None:
    """Configures logging"""
    # Check if running on container
    logging.root.setLevel(level)

    if not colorlog_enable:
        formatter = logging.Formatter(
            "  %(levelname)-7s  |  %(name)-11s  |  %(message)s"
        )
    else:
        formatter = colorlog.ColoredFormatter(
            "  %(log_color)s%(levelname)-7s%(reset)s  |  "
            "%(name)-11s  |  %(log_color)s%(message)s%(reset)s"
        )

    stream = logging.StreamHandler()
    stream.setLevel(level)
    stream.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(stream)

    logging.getLogger("pyrogram").setLevel(logging.ERROR)

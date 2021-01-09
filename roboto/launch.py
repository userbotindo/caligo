import logging

from .core import roboto

log = logging.getLogger("launch")


def main():
    log.info("Initializing roboto...")
    _log = logging.getLogger("pyrogram")
    _log.setLevel(logging.WARNING)
    roboto.go()

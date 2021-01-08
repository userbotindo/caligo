import logging

from .core import RobOto

log = logging.getLogger("launch")
roboto = RobOto()


def main():
    log.info("Initializing roboto...")
    _log = logging.getLogger("pyrogram")
    _log.setLevel(logging.WARNING)
    roboto.go()

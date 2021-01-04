import logging


from RobOto import roboto
from RobOto.core.logging import setup_log


if __name__ == "__main__":
    _LOG = logging.getLogger("pyrogram")
    _LOG.setLevel(logging.WARNING)
    setup_log()
    roboto.go()

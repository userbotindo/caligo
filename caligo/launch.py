import asyncio
import logging

import aiorun

from .core import Bot

log = logging.getLogger("Launch")
aiorun.logger.disabled = True


def main() -> None:
    """Main entry point for the default bot launcher."""

    log.info("Initializing bot")

    try:
        import uvloop
    except ImportError:
        pass
    else:
        uvloop.install()
        log.info("Using uvloop event loop")

    loop = asyncio.new_event_loop()
    aiorun.run(Bot.create_and_run(loop=loop), loop=loop)

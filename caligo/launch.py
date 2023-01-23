import asyncio
import logging
import sys
from typing import Any, MutableMapping

import aiorun

from .core import Caligo

log = logging.getLogger("Launch")
aiorun.logger.disabled = True


def main(config: MutableMapping[str, Any]) -> None:
    """Main entry point for the default bot launcher."""

    if sys.platform == "win32":
        policy = asyncio.WindowsProactorEventLoopPolicy()
        asyncio.set_event_loop_policy(policy)
    else:
        try:
            import uvloop
        except ImportError:
            pass
        else:
            uvloop.install()
            log.info("Using uvloop event loop")

    log.info("Initializing bot")
    loop = asyncio.new_event_loop()

    aiorun.run(Caligo.create_and_run(config, loop=loop), loop=loop)

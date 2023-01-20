import asyncio
import logging
import sys
from pathlib import Path

import aiorun
import tomllib

from .core import Caligo

log = logging.getLogger("Launch")
aiorun.logger.disabled = True


def main() -> None:
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

    config_path = Path("config.toml")
    if not config_path.exists():
        raise RuntimeError("Configuration must be done before running the bot.")

    with config_path.open(mode="rb") as f:
        config = tomllib.load(f)

    aiorun.run(Caligo.create_and_run(config, loop=loop), loop=loop)

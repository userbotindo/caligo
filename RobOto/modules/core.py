import pyrogram
import logging

from .system import System
from pyrogram.filters import me, edited, command as cmd
from RobOto import roboto, command

LOG = logging.getLogger("RobOto.Modules")


class Module(System):
    """Core module"""


@roboto.command(
    cmd("help", ".", case_sensitive=True) &
    ~edited &
    me
)
@command.desc("Parse all command help")
@command.usage(".help")
async def cmd_help(client: roboto, message: pyrogram.types.Message) -> None:
    """ TO-DO """

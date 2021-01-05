import pyrogram
import logging

from .system import System
from pyrogram.filters import me, edited, command as cmd, channel
from RobOto import roboto, command

LOG = logging.getLogger("RobOto.Modules")


class Module(System):
    """Core module"""

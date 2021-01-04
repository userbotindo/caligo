from .command import Command
from .command_ext import CommandExt


class Decorator(Command, CommandExt):
    pass

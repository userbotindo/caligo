import re

from typing import Union, List, Optional

from pyrogram.filters import create
from pyrogram.types import Message


class CustomCommandFilter:

    def command(
        self,
        commands: Union[str, List[str]],
        prefixes: Union[str, List[str]],
        desc: Optional[str],
        usage: Optional[str],
        case_sensitive: bool = True
    ):
        command_re = re.compile(r"([\"'])(.*?)(?<!\\)\1|(\S+)")

        async def func(flt, self, message: Message):
            text = message.text or message.caption
            self.cmd = None
            self.cmd_desc = flt.desc
            self.cmd_usage = flt.desc

            if not text:
                return False

            pattern = r"^{}(?:\s|$)" if flt.case_sensitive else r"(?i)^{}(?:\s|$)"

            for prefix in flt.prefixes:
                if not text.startswith(prefix):
                    continue

                without_prefix = text[len(prefix):]

                for cmd in flt.commands:
                    if not re.match(pattern.format(re.escape(cmd)), without_prefix):
                        continue

                    self.cmd = [cmd] + [
                        re.sub(r"\\([\"'])", r"\1", m.group(2) or m.group(3) or "")
                        for m in command_re.finditer(without_prefix[len(cmd):])
                    ]

                    return True

            return False

        commands = commands if isinstance(commands, list) else [commands]
        commands = {c if case_sensitive else c.lower() for c in commands}

        prefixes = [] if prefixes is None else prefixes
        prefixes = prefixes if isinstance(prefixes, list) else [prefixes]
        prefixes = set(prefixes) if prefixes else {""}

        return create(
            func,
            "CustomCommandFilter",
            commands=commands,
            prefixes=prefixes,
            desc=desc,
            usage=usage,
            case_sensitive=case_sensitive
        )

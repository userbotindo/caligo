import os

from typing import Union
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class BotConfig:
    """
    Bot configuration
    """

    def __init__(self) -> Union[str, int]:
        if os.path.isfile("config.env"):
            load_dotenv("config.env")

        # Core config
        self.api_id = int(os.environ.get("API_ID", 0))
        self.api_hash = os.environ.get("API_HASH")
        self.string_session = os.environ.get("STRING_SESSION")

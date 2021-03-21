import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class BotConfig:
    """
    Bot configuration
    """

    def __init__(self) -> "BotConfig":
        if os.path.isfile("config.env"):
            load_dotenv("config.env")

        # Core config
        self.api_id = int(os.environ.get("API_ID", 0))
        self.api_hash = os.environ.get("API_HASH")
        self.db_uri = os.environ.get("DB_URI")
        self.string_session = os.environ.get("STRING_SESSION")

        # GoogleDrive
        try:
            self.gdrive_secret = json.loads(os.environ.get("G_DRIVE_SECRET"))
        except (TypeError, json.decoder.JSONDecodeError):
            self.gdrive_secret = None
        self.gdrive_folder_id = os.environ.get("G_DRIVE_FOLDER_ID")
        self.gdrive_index_link = os.environ.get("G_DRIVE_INDEX_LINK")

        # Checker
        self.secret = bool(os.environ.get("CONTAINER") == "True")

        # Github
        self.github_repo = os.environ.get("GITHUB_REPO")
        self.github_token = os.environ.get("GITHUB_TOKEN")

        # Heroku
        self.heroku_app_name = os.environ.get("HEROKU_APP")
        self.heroku_api_key = os.environ.get("HEROKU_API_KEY")

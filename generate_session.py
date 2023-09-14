import asyncio
import os
import tomli
from pyrogram.client import Client
from caligo.core import database


def load_config(filename: str) -> dict:
    # Check if the file exists and is readable
    if os.path.isfile(filename) and os.access(filename, os.R_OK):
        # Load the configuration from the file in binary mode
        with open(filename, "rb") as config_file:
            config = tomli.load(config_file)
    else:
        # Return an empty dictionary if the file is not found or not readable
        config = {}
    return config

# Define a function to get a value from the configuration or return None
def get_config_value(config: dict, section: str, key: str) -> str:
    # Try to get the value from the configuration dictionary
    value = config.get(section, {}).get(key)
    # Return the value or None if not found or empty
    return value or None

async def create_session() -> None:
    # Load the configuration from config.toml
    config = load_config("config.toml")

    # Get the values for api_id, api_hash, and mongodb_uri from the configuration or return None
    api_id = get_config_value(config, "telegram", "api_id")
    api_hash = get_config_value(config, "telegram", "api_hash")
    mongodb_uri = get_config_value(config, "bot", "db_uri")

    # Prompt the user for input only if the value is None
    if api_id is None:
        api_id = input("Please enter Telegram API ID: ")
    if api_hash is None:
        api_hash = input("Please enter Telegram API HASH: ")
    if mongodb_uri is None:
        mongodb_uri = input("Please enter MongoDB URI: ")

    # Create a Pyrogram client with the given parameters
    client = Client(
        api_id=api_id,
        api_hash=api_hash,
        name="caligo",
        workdir="caligo",
    )
    
    # Create a MongoDB client with the given URI and connect lazily
    db_client = database.AsyncClient(mongodb_uri, connect=False)
    
    # Get the CALIGO database from the MongoDB client
    db = db_client.get_database("CALIGO")
    
    # Set the persistent storage for the Pyrogram client using the database
    client.storage = database.storage.PersistentStorage(db)  # type: ignore

    print("Generating session...")
    
    # Start and stop the Pyrogram client to generate a session file
    await client.start()
    print("Session generated successfully!")
    await client.stop()
    
    # Close the MongoDB client connection
    await db_client.close()

if __name__ == "__main__":
    asyncio.run(create_session())

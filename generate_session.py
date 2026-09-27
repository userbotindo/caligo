import asyncio
import os
from typing import Any, Dict, Optional

try:
    import dns.resolver
    try:
        import dns.asyncresolver
    except ImportError:
        dns.asyncresolver = None  # type: ignore

    if not os.path.exists("/etc/resolv.conf"):
        prefix_resolv = os.path.join(
            os.environ.get("PREFIX", "/data/data/com.termux/files/usr"),
            "etc",
            "resolv.conf",
        )
        if os.path.exists(prefix_resolv):
            dns.resolver.default_resolver = dns.resolver.Resolver(
                filename=prefix_resolv
            )
            if dns.asyncresolver is not None:
                dns.asyncresolver.default_resolver = dns.asyncresolver.Resolver(
                    filename=prefix_resolv
                )
        else:
            r = dns.resolver.Resolver(configure=False)
            r.nameservers = ["8.8.8.8", "1.1.1.1"]
            dns.resolver.default_resolver = r
            if dns.asyncresolver is not None:
                ar = dns.asyncresolver.Resolver(configure=False)
                ar.nameservers = ["8.8.8.8", "1.1.1.1"]
                dns.asyncresolver.default_resolver = ar
except (ImportError, Exception):
    pass

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

from pyrogram.client import Client
from caligo.core import database


def load_config(filename: str) -> Dict[str, Any]:
    # Check if the file exists and is readable
    if os.path.isfile(filename) and os.access(filename, os.R_OK):
        # Load the configuration from the file in binary mode
        with open(filename, "rb") as config_file:
            config = tomllib.load(config_file)
    else:
        # Return an empty dictionary if the file is not found or not readable
        config = {}
    return config


# Define a function to get a value from the configuration or return None
def get_config_value(config: dict, section: str, key: str) -> Optional[Any]:
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
    while api_id is None:
        raw_api_id = input("Please enter Telegram API ID: ").strip()
        if raw_api_id.isdigit():
            api_id = int(raw_api_id)
        else:
            print("API ID must be an integer. Please try again.")

    api_id = int(api_id)

    if api_hash is None:
        api_hash = input("Please enter Telegram API HASH: ").strip()
    else:
        api_hash = str(api_hash).strip()

    if mongodb_uri is None:
        mongodb_uri = input("Please enter MongoDB URI: ").strip()
    else:
        mongodb_uri = str(mongodb_uri).strip()

    os.makedirs("caligo", exist_ok=True)

    # Create a MongoDB client with the given URI and connect lazily
    db_client = database.AsyncClient(mongodb_uri, connect=False)
    try:
        # Get the CALIGO database from the MongoDB client
        db = db_client.get_database("CALIGO")

        # Set persistent storage for the Kurigram client using the database
        storage = database.PersistentStorage(db)

        # Create a Kurigram client with the given parameters and custom storage
        client = Client(
            api_id=api_id,
            api_hash=api_hash,
            name="caligo",
            workdir="caligo",
            storage_engine=storage,
        )
        client.storage = storage

        print("Generating session...")

        # Start and stop the Kurigram client to generate and save session to database
        await client.start()
        print("Session generated successfully!")
        await client.stop()
    finally:
        # Close the MongoDB client connection
        await db_client.close()


if __name__ == "__main__":
    asyncio.run(create_session())


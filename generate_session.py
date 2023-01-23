import asyncio

from pyrogram.client import Client

from caligo.core import database


async def create_session() -> None:
    client = Client(
        api_id=input("Please enter Telegram API ID: "),
        api_hash=input("Please enter Telegram API HASH: "),
        name="caligo",
        workdir="caligo",
    )
    db_client = database.AsyncClient(input("Please enter MongoDB URI: "), connect=False)
    db = db_client.get_database("CALIGO")
    client.storage = database.storage.PersistentStorage(db)  # type: ignore

    print("Generating session...")
    await client.start()
    print("Session generated successfully!")
    await client.stop()
    await db_client.close()


if __name__ == "__main__":
    asyncio.run(create_session())

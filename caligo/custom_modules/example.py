import asyncio
import io
import sys
from typing import BinaryIO, ClassVar

if sys.version_info >= (3, 10):
    from aiopath import AsyncPurePosixPath as PosixPath
else:
    from aiopath import PureAsyncPosixPath as PosixPath

from pyrogram.types import Message

from caligo import command, listener, module
from caligo.core import database


class ExampleModule(module.Module):
    name: ClassVar[str] = "Example"
    disabled: ClassVar[bool] = True
    helpable: ClassVar[bool] = False

    db: database.AsyncCollection

    async def on_load(self) -> None:
        self.db = self.bot.db.get_collection("example")

    @listener.priority(50)  # The less the number, the higher the priority
    async def on_message(self, message: Message) -> None:
        self.log.info(f"Received message: {message.text}")
        await self.db.update_one(
            {"_id": message.id}, {"$set": {"text": message.text}}, upsert=True
        )

    async def on_message_delete(self, message: Message) -> None:
        self.log.info(f"Message deleted: {message.text}")
        await self.db.delete_one({"_id": message.id})

    async def on_chat_action(self, message: Message) -> None:
        if message.new_chat_members:
            for new_member in message.new_chat_members:
                self.log.info("New member joined: %s", new_member.first_name)
        else:
            left_member = message.left_chat_member
            self.log.info("A member just left chat: %s", left_member.first_name)

    async def cmd_test(self, ctx: command.Context) -> str:
        await ctx.respond("Processing...")
        await asyncio.sleep(1)

        if ctx.input:
            return ctx.input

        return "It works!"

    async def get_cat(self) -> BinaryIO:
        # Get the link to a random cat picture
        async with self.bot.http.get("https://aws.random.cat/meow") as resp:
            # Read and parse the response as JSON
            json = await resp.json()
            # Get the "file" field from the parsed JSON object
            cat_url = json["file"]

        # Get the actual cat picture
        async with self.bot.http.get(cat_url) as resp:
            # Get the data as a byte array (bytes object)
            cat_data = await resp.read()

        # Construct a byte stream from the data.
        # This is necessary because the bytes object is immutable, but we need to add a "name" attribute to set the
        # filename. This facilitates the setting of said attribute without altering behavior.
        cat_stream = io.BytesIO(cat_data)

        # Set the name of the cat picture before sending.
        # This is necessary for Pyrogram to detect the file type and send it as a photo/GIF rather than just a plain
        # unnamed file that doesn't render as media in clients.
        # We abuse aiopath to extract the filename section here for convenience, since URLs are *mostly* POSIX paths
        # with the exception of the protocol part, which we don't care about here.
        cat_stream.name = PosixPath(cat_url).name

        return cat_stream

    async def cmd_cat(self, ctx: command.Context) -> None:
        await ctx.respond("Fetching cat...")
        cat_stream = await self.get_cat()

        await self.bot.client.send_animation(
            ctx.chat.id, cat_stream, message_thread_id=ctx.msg.message_thread_id
        )

from pyrogram import Client


class Base(Client):

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

from pyrogram import Client


class RawClient(Client):

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

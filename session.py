from argparse import ArgumentParser, RawTextHelpFormatter
from pyrogram import Client, asyncio


async def Session(mode: str) -> None:
    async with Client(
        "roboto",
        api_id=input("Please enter Telegram API ID: "),
        api_hash=input("Please enter Telegram API HASH: "),
        workdir='caligo'
    ) as roboto:
        print("Generating...")
        print()
        if mode == "stdout":
            print(await roboto.export_session_string())
            print()
        else:
            await roboto.send_message(
                "me", f"```{await roboto.export_sessiong_string()}```")
        print("Generated")


if __name__ == "__main__":
    parser = ArgumentParser(description='Generate Session Telegram',
                            formatter_class=RawTextHelpFormatter)
    parser.add_argument(
        "-m",
        "--mode",
        metavar="STDOUT",
        type=str,
        choices=("stdout", "message"),
        default="stdout",
        help=("choices: {%(choices)s}\n"
              "stdout: output session string into stdout\n"
              "message: output session string into saved message"
              )
    )

    args = parser.parse_args()
    asyncio.get_event_loop().run_until_complete(Session(mode=args.mode))

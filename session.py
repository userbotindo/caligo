"""Standalone Session String generator"""
# Copyright (C) 2021 Adek Maulana
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# This script only to generate your Session not running the bot.
from argparse import ArgumentParser, RawTextHelpFormatter

from pyrogram import Client, asyncio


async def Session(mode: str) -> None:
    async with Client(
        "caligo",
        api_id=input("Please enter Telegram API ID: "),
        api_hash=input("Please enter Telegram API HASH: "),
        workdir='caligo'
    ) as caligo:
        print("Generating...")
        print()
        if mode == "stdout":
            print(await caligo.export_session_string())
            print()
        else:
            await caligo.send_message(
                "me", f"```{await caligo.export_sessiong_string()}```")
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

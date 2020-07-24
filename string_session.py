# Copyright (C) 2020 Adek Maulana
#
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import asyncio

from pyrogram import Client


async def generateStringSession():
    print("Getting information...")
    async with Client(
        "bishproject",
        api_id=int(input("Enter API ID: ")),
        api_hash=input("Enter API HASH: ")
    ) as bishproject:
        print()
        print("Sending and pulling information...")
        await bishproject.send_message(
            "me", ("#SESSION:\n\n"
                   f"```{bishproject.export_session_string()}```"))
        print("Sent!, into your saved messages.")

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(generateStringSession())

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
from pyrogram import Client


print("Getting information...")
with Client(
    "bishproject",
    api_id=int(input("Enter API ID: ")),
    api_hash=input("Enter API HASH: ")
) as bishproject:
    print()
    print("Sending and pulling information...")
    bishproject.send_message(
        "me", ("**StringSession**:\n\n"
               f"```{bishproject.export_session_string()}```"))
    print("Information saved into your saved messages.")

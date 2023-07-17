import asyncio
import json
from typing import Any, ClassVar, Dict, List

from caligo import command, listener, module


class Magisk(module.Module):
    """A module for fetching information about Magisk."""

    name: ClassVar[str] = "Magisk"
    disabled: ClassVar[bool] = False
    helpable: ClassVar[bool] = True

    async def fetch_json(self, url: str) -> Dict[str, Any]:
        """Fetch JSON data from the specified URL.

        Args:
            url (str): The URL to fetch data from.

        Returns:
            Dict[str, Any]: The JSON data as a dictionary.
        """
        async with self.bot.http.get(url) as response:
            if response.headers['Content-Type'] == 'application/json':
                return await response.json()
            elif response.headers['Content-Type'] == 'text/plain; charset=utf-8':
                text = await response.text()
                return json.loads(text)
            else:
                raise Exception(f'Unexpected mimetype: {response.headers["Content-Type"]}')

    @command.desc("Get the version, download link, and release notes of Magisk from different sources")
    @command.usage("magisk")
    async def cmd_magisk(self, ctx: command.Context) -> None:
        """Get the version, download link, and release notes of Magisk from different sources.

        Args:
            ctx (command.Context): The command context.
        """
        urls = {
            "Beta": "https://raw.githubusercontent.com/topjohnwu/magisk-files/master/beta.json",
            "Stable": "https://raw.githubusercontent.com/topjohnwu/magisk-files/master/stable.json",
            "Canary": "https://raw.githubusercontent.com/topjohnwu/magisk-files/master/canary.json",
            "Debug": "https://raw.githubusercontent.com/topjohnwu/magisk-files/master/debug.json",
        }
        tasks = {}
        for tag, url in urls.items():
            task = asyncio.create_task(self.fetch_json(url))
            tasks[tag] = task
        try:
            results = await asyncio.gather(*tasks.values())
            json_data_dict = dict(zip(tasks.keys(), results))
        except Exception as e:
            await ctx.respond(f"An error occurred while fetching data: {e}")
            return

        # Access the data using the keys
        response_text = ""
        sorted_tags = sorted(tasks.keys())
        for tag in sorted_tags:
            json_data = json_data_dict[tag]
            magisk_version = json_data["magisk"]["version"]
            magisk_link = json_data["magisk"]["link"]
            magisk_note = json_data["magisk"]["note"]
            response_text += f"**Magisk:** {tag}\n**Version:** `{magisk_version}`\n[Download link]({magisk_link})\n[Release notes]({magisk_note})\n\n"
        await ctx.respond(response_text.strip())

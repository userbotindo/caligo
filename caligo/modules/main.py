import asyncio
import platform
import re
import uuid
from collections import defaultdict
from hashlib import sha256
from typing import ClassVar, List, MutableMapping

from anyio import Path as AsyncPath
from bson.binary import Binary
from pymongo.asynchronous.collection import AsyncCollection
import pyrogram
from pyrogram import errors, filters, types
from pyrogram.enums import ButtonStyle, ParseMode

from caligo import __version__, command, listener, module, util


class Main(module.Module):
    name: ClassVar[str] = "Main"

    db: AsyncCollection

    _module_command_map: MutableMapping[str, MutableMapping[str, str]]
    _all_modules: List[str]
    _modules_per_page: int
    _total_pages: int
    _prebuilt_buttons: MutableMapping[int, List[List[types.InlineKeyboardButton]]]

    async def on_load(self) -> None:
        self.db = self.bot.db[self.name.upper()]
        self._build_command_map()

    def _build_command_map(self) -> None:
        self._module_command_map = defaultdict(dict)
        for _, cmd in self.bot.commands.items():
            mod_name = cmd.module.name
            desc = cmd.desc or "<i>No description provided.</i>"
            aliases = f' (aliases: {", ".join(cmd.aliases)})' if cmd.aliases else ""
            self._module_command_map[mod_name][cmd.name] = desc + aliases

        self._all_modules = sorted(self._module_command_map.keys())
        self._modules_per_page = 8  # 4 rows × 2 buttons per row
        self._total_pages = max(
            1,
            (len(self._all_modules) + self._modules_per_page - 1)
            // self._modules_per_page,
        )

        self._prebuilt_buttons = {}
        for page in range(self._total_pages):
            self._prebuilt_buttons[page] = self.build_button(page)

    def get_menu_text(self) -> str:
        sys_ver = platform.release()
        try:
            sys_ver = sys_ver[: sys_ver.index("-")]
        except ValueError:
            pass

        return (
            "<b>Caligo Menu Helper</b>\n\n"
            f"• <b>Version:</b> <code>v{__version__}</code>\n"
            f"• <b>System:</b> <code>{platform.system()} {sys_ver}</code>\n"
            f"• <b>Python:</b> <code>{platform.python_version()}</code>"
        )

    def build_button(self, page: int = 0) -> List[List[types.InlineKeyboardButton]]:
        """Build paginated buttons with 2 buttons per row using ButtonStyle colors"""
        buttons = []

        start_idx = page * self._modules_per_page
        end_idx = min(start_idx + self._modules_per_page, len(self._all_modules))
        current_modules = self._all_modules[start_idx:end_idx]

        # Create module buttons (2 per row) styled with primary color
        for i in range(0, len(current_modules), 2):
            row = []
            for j in range(2):
                if i + j < len(current_modules):
                    mod = current_modules[i + j]
                    row.append(
                        types.InlineKeyboardButton(
                            mod,
                            callback_data=f"menu({mod})",
                            style=ButtonStyle.PRIMARY,
                        )
                    )
            buttons.append(row)

        # Add navigation buttons if we have more than one page
        if self._total_pages > 1:
            nav_row = []

            # Previous button (Primary)
            prev_page = page - 1 if page > 0 else self._total_pages - 1
            nav_row.append(
                types.InlineKeyboardButton(
                    "«",
                    callback_data=f"menu_page({prev_page})",
                    style=ButtonStyle.PRIMARY,
                )
            )

            # Page indicator (Default)
            nav_row.append(
                types.InlineKeyboardButton(
                    f"{page + 1}/{self._total_pages}",
                    callback_data="noop",
                    style=ButtonStyle.DEFAULT,
                )
            )

            # Next button (Primary)
            next_page = page + 1 if page < self._total_pages - 1 else 0
            nav_row.append(
                types.InlineKeyboardButton(
                    "»",
                    callback_data=f"menu_page({next_page})",
                    style=ButtonStyle.PRIMARY,
                )
            )

            buttons.append(nav_row)

        # Add close button at bottom (Danger / Red)
        buttons.append(
            [
                types.InlineKeyboardButton(
                    "✗ Close",
                    callback_data="menu(Close)",
                    style=ButtonStyle.DANGER,
                )
            ]
        )

        return buttons

    async def on_stop(self) -> None:
        file = AsyncPath("caligo/caligo_helper.session")
        if not await file.exists():
            return

        await self.bot.db.get_collection("SESSION_HELPER").update_one(
            {
                "_id": sha256(
                    str(self.bot.config["telegram"]["api_id"]).encode()
                ).hexdigest()
            },
            {
                "$set": {
                    "session": Binary(await file.read_bytes()),
                }
            },
            upsert=True,
        )

    async def on_inline_query(self, query: types.InlineQuery) -> None:
        if query.query and query.query.strip().lower() not in {"", "help"}:
            return

        results = [
            types.InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="About Caligo",
                input_message_content=types.InputTextMessageContent(
                    "<i>Caligo Simple. Powerful. Yours...</i>",
                    parse_mode=ParseMode.HTML,
                ),
                description="Caligo Simple. Powerful. Yours..",
                reply_markup=types.InlineKeyboardMarkup(
                    [
                        [
                            types.InlineKeyboardButton(
                                "⚡️ Owner", user_id=self.bot.uid
                            ),
                            types.InlineKeyboardButton(
                                "📖️ Discussion", url="t.me/deltaDiscuss"
                            ),
                        ],
                        [
                            types.InlineKeyboardButton(
                                "ℹ️ Updates", url="https://execnow.t.me"
                            )
                        ],
                    ]
                ),
            )
        ]

        if query.from_user and query.from_user.id == self.bot.uid:
            if not hasattr(self, "_prebuilt_buttons") or not self._prebuilt_buttons:
                self._build_command_map()

            menu_buttons = self._prebuilt_buttons.get(0, self.build_button(0))
            results.append(
                types.InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title="Menu",
                    input_message_content=types.InputTextMessageContent(
                        self.get_menu_text(),
                        parse_mode=ParseMode.HTML,
                    ),
                    description="Menu Helper.",
                    reply_markup=types.InlineKeyboardMarkup(menu_buttons),
                )
            )

        await query.answer(results=results, cache_time=5)

    @listener.priority(90)
    @listener.filters(filters.regex(r"^menu(?:_page)?\((.+)\)$"))
    async def on_callback_query(self, query: types.CallbackQuery) -> None:
        if query.from_user and query.from_user.id != self.bot.uid:
            await query.answer("Not For You!", show_alert=True)
            return

        match = re.match(r"^menu(?:_page)?\((.+)\)$", query.data)
        if not match:
            return

        action_or_page = match.group(1)

        if not hasattr(self, "_prebuilt_buttons") or not self._prebuilt_buttons:
            self._build_command_map()

        if query.data.startswith("menu_page("):
            try:
                page = int(action_or_page)
                menu_buttons = self._prebuilt_buttons.get(
                    page, self.build_button(page)
                )
                await query.edit_message_text(
                    self.get_menu_text(),
                    reply_markup=types.InlineKeyboardMarkup(menu_buttons),
                    parse_mode=ParseMode.HTML,
                )
            except (ValueError, errors.MessageNotModified):
                pass
            except errors.FloodWait as e:
                await asyncio.sleep(e.value + 1)
            return

        if action_or_page == "noop":
            await query.answer("Caligo Menu")
            return

        mod = action_or_page

        if mod == "Back":
            try:
                menu_buttons = self._prebuilt_buttons.get(0, self.build_button(0))
                await query.edit_message_text(
                    self.get_menu_text(),
                    reply_markup=types.InlineKeyboardMarkup(menu_buttons),
                    parse_mode=ParseMode.HTML,
                )
            except errors.MessageNotModified:
                pass
            except errors.FloodWait as e:
                await asyncio.sleep(e.value + 1)
            return

        if mod == "Close":
            try:
                if query.inline_message_id:
                    chat_id, msg_id = await util.tg.unpack_inline_id(
                        self.bot.uid, query.inline_message_id
                    )
                    await self.bot.client.delete_messages(chat_id, msg_id)
                elif query.message:
                    await query.message.delete()
            except errors.ChatIdInvalid:
                await query.answer("😿️ Couldn't close message")
                menu_buttons = self._prebuilt_buttons.get(0, self.build_button(0))
                menu_buttons = menu_buttons[:-1]
                await query.edit_message_text(
                    self.get_menu_text(),
                    reply_markup=types.InlineKeyboardMarkup(menu_buttons),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                self.log.error("Error closing message: %s", e)
                await query.answer("😿️ Error closing message")
            return

        commands = self._module_command_map.get(mod)
        if not commands:
            await query.answer(f"😿️ {mod} doesn't have any commands.")
            return

        response = util.text.join_map(commands, heading=mod, parse_mode="html")

        # Back button styled with Success / Green
        back_button = [
            [
                types.InlineKeyboardButton(
                    "⇠ Back",
                    callback_data="menu(Back)",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        ]
        try:
            await query.edit_message_text(
                f"<blockquote expandable>{response}</blockquote>",
                reply_markup=types.InlineKeyboardMarkup(back_button),
                parse_mode=ParseMode.HTML,
            )
        except errors.MessageNotModified:
            pass
        except errors.FloodWait as e:
            await asyncio.sleep(e.value + 1)

    @command.desc("List the commands")
    @command.usage("[filter: command or module name?]", optional=True)
    async def cmd_help(self, ctx: command.Context) -> Optional[str]:
        filt = ctx.input

        if self.bot.helper_initialized and not filt:
            try:
                bot_user = (
                    getattr(self.bot, "bot_user", None)
                    or self.bot.client_helper.me
                    or await self.bot.client_helper.get_me()
                )
                if not bot_user or not bot_user.username:
                    raise ValueError("Helper bot has no username")

                response = await self.bot.client.get_inline_bot_results(
                    bot=bot_user.username
                )
            except errors.BotInlineDisabled:
                return "<i>Bot Inline Disabled. Enable it via @BotFather with /setinline</i>"
            except Exception as e:
                self.log.warning(
                    "Inline help lookup failed, falling back to text: %s", e
                )
            else:
                if response and response.results:
                    await ctx.msg.delete()
                    result_id = (
                        response.results[1].id
                        if len(response.results) > 1
                        else response.results[0].id
                    )
                    if ctx.chat.is_forum:
                        await self.bot.client.send_inline_bot_result(
                            ctx.msg.chat.id,
                            response.query_id,
                            result_id,
                            message_thread_id=ctx.msg.message_thread_id,
                        )
                    else:
                        try:
                            await self.bot.client.send_inline_bot_result(
                                ctx.msg.chat.id, response.query_id, result_id
                            )
                        except errors.FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                            await self.bot.client.send_inline_bot_result(
                                ctx.msg.chat.id, response.query_id, result_id
                            )
                    return None

        # Handle command filters
        if filt and filt not in self.bot.modules:
            if filt in self.bot.commands:
                cmd = self.bot.commands[filt]

                aliases = (
                    f"<code>{'</code>, <code>'.join(cmd.aliases)}</code>"
                    if cmd.aliases
                    else None
                )

                args_desc = None
                if cmd.usage:
                    args_desc = cmd.usage
                    if cmd.usage_optional:
                        args_desc += " (optional)"
                    if cmd.usage_reply:
                        args_desc += " (also accepts replies)"

                data = {
                    "Command": f"<code>{cmd.name}</code>",
                    "Description": cmd.desc or "<i>No description provided.</i>",
                    "Module": cmd.module.name,
                }
                if aliases:
                    data["Aliases"] = aliases
                if args_desc:
                    data["Expected parameters"] = args_desc

                response = util.text.join_map(data, parse_mode="html")

                return (
                    f"<b>Help for <code>{cmd.name}</code></b>"
                    f"<blockquote expandable>\n{response}\n</blockquote>"
                )

            return "<i>That filter didn't match any commands or modules.</i>"

        # Show full help text fallback
        modules: MutableMapping[str, MutableMapping[str, str]] = defaultdict(dict)
        for name, cmd in self.bot.commands.items():
            if filt:
                if cmd.module.name != filt:
                    continue
            else:
                if name != cmd.name:
                    continue

            desc = cmd.desc or "<i>No description provided</i>"
            aliases = f' (aliases: {", ".join(cmd.aliases)})' if cmd.aliases else ""
            mod_name = type(cmd.module).name
            modules[mod_name][cmd.name] = desc + aliases

        response_sections = []
        for mod_name, commands in sorted(modules.items()):
            section = util.text.join_map(commands, heading=mod_name, parse_mode="html")
            response_sections.append(section)

        full_response = "\n\n".join(response_sections)
        await ctx.respond(
            text=f"<blockquote expandable>\n{full_response}\n</blockquote>",
            parse_mode=ParseMode.HTML,
        )
        return None

    @command.desc("Get or change this bot prefix")
    @command.alias("setprefix", "getprefix")
    @command.usage("[new prefix?]", optional=True)
    async def cmd_prefix(self, ctx: command.Context) -> str:
        new_prefix = ctx.input

        if not new_prefix:
            return f"The prefix is <code>{self.bot.prefix}</code>"

        self.bot.prefix = new_prefix
        await self.db.update_one(
            {"_id": 0},
            {"$set": {"prefix": new_prefix}},
            upsert=True,
        )

        return f"Prefix set to <code>{self.bot.prefix}</code>"

    @command.desc("Get information about this bot instance")
    @command.alias("botinfo", "binfo", "bi", "i")
    async def cmd_info(self, ctx: command.Context) -> None:
        # Get tagged version and optionally the Git commit
        commit = await util.run_sync(util.version.get_commit)
        dirty = ", dirty" if await util.run_sync(util.git.is_dirty) else ""
        unofficial = (
            ", unofficial" if not await util.run_sync(util.git.is_official) else ""
        )
        version = (
            f"{__version__} (<code>{commit}</code>{dirty}{unofficial})"
            if commit
            else __version__
        )

        # Clean system version
        sys_ver = platform.release()
        try:
            sys_ver = sys_ver[: sys_ver.index("-")]
        except ValueError:
            pass

        # Get current uptime
        now = util.time.usec()
        uptime = util.time.format_duration_us(now - self.bot.start_time_us)

        # Get total uptime from stats module (if loaded)
        stats_module = self.bot.modules.get("Stats", None)
        get_start_time = getattr(stats_module, "get_start_time", None)
        total_uptime = None
        if stats_module is not None and callable(get_start_time):
            stats_start_time = await get_start_time()
            total_uptime = util.time.format_duration_us(now - stats_start_time) + "\n"
        else:
            uptime += "\n"

        # Get total number of chats, including PMs
        num_chats = await self.bot.client.get_dialogs_count()

        response = util.text.join_map(
            {
                "Version": version,
                "Kurigram": pyrogram.__version__,
                "Python": f"{platform.python_implementation()} {platform.python_version()}",
                "System": f"{platform.system()} {sys_ver}",
                "Uptime": uptime,
                **({"Total uptime": total_uptime} if total_uptime else {}),
                "Commands loaded": len(self.bot.commands),
                "Modules loaded": len(self.bot.modules),
                "Listeners loaded": sum(
                    len(evt) for evt in self.bot.listeners.values()
                ),
                "Events activated": f"{self.bot.events_activated}\n",
                "Chats": num_chats,
            },
            heading='<a href="https://github.com/adekmaulana/caligo">Caligo</a> info',
            parse_mode="html",
        )

        await ctx.respond(response, parse_mode=ParseMode.HTML)

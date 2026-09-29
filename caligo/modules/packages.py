import html
import urllib.parse
import uuid
from typing import Any, ClassVar, Dict, List, Optional, Tuple

import httpx
from pyrogram import types
from pyrogram.enums import ParseMode

from caligo import command, module, util


def _clean_url(url: Optional[str]) -> Optional[str]:
    """Ensure URL is a valid HTTP/HTTPS/TG URL acceptable by Telegram buttons."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if url.startswith("git+https://"):
        url = url[4:]
    elif url.startswith("git+http://"):
        url = url[4:]
    elif url.startswith("git://"):
        url = "https://" + url[6:]
    elif url.startswith("git@github.com:"):
        url = "https://github.com/" + url[15:]
    elif url.startswith("github.com/"):
        url = "https://" + url

    if not url.startswith(("http://", "https://", "tg://")):
        return None
    return url


class Packages(module.Module):
    name: ClassVar[str] = "Packages"

    async def _http_get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 12.0,
    ) -> Optional[httpx.Response]:
        http: Optional[httpx.AsyncClient] = getattr(self.bot, "http", None)
        req_headers = {"User-Agent": "Mozilla/5.0"}
        if headers:
            req_headers.update(headers)
        try:
            if http is not None:
                return await http.get(url, params=params, headers=req_headers, timeout=timeout)
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
                return await client.get(url, params=params, headers=req_headers)
        except Exception as e:
            self.log.debug("HTTP GET error for %s: %s", url, e)
            return None

    # -------------------------------------------------------------------------
    # PyPI Lookup
    # -------------------------------------------------------------------------
    async def _get_pypi_data(self, query: str) -> Optional[Tuple[str, List[List[types.InlineKeyboardButton]]]]:
        raw = query.strip().lower()
        candidates: List[str] = [
            raw,
            raw.replace(" ", "-"),
            raw.replace(" ", "_"),
            raw.replace("_", "-"),
            raw.replace("-", "_"),
        ]
        if " " not in raw:
            candidates.extend(
                [
                    f"python-{raw}",
                    f"py-{raw}",
                    f"{raw}-py",
                    f"{raw}-python",
                    f"{raw}-bot",
                ]
            )

        unique_candidates: List[str] = []
        for c in candidates:
            if c and c not in unique_candidates:
                unique_candidates.append(c)

        matched_data: Optional[Dict[str, Any]] = None
        for candidate in unique_candidates:
            encoded = urllib.parse.quote(candidate)
            url = f"https://pypi.org/pypi/{encoded}/json"
            resp = await self._http_get(url)
            if resp is not None and resp.status_code == 200:
                try:
                    matched_data = resp.json()
                    break
                except Exception:
                    continue

        if not matched_data:
            return None

        info = matched_data.get("info", {})
        name = info.get("name") or query
        version = info.get("version") or "unknown"
        summary = info.get("summary") or "No description provided."
        author = (
            info.get("author")
            or info.get("maintainer")
            or info.get("author_email")
            or "Unknown"
        )
        license_str = info.get("license") or "Not specified"
        if len(license_str) > 35:
            license_str = license_str[:32] + "..."
        py_version = info.get("requires_python") or "Any"
        pkg_url = _clean_url(info.get("package_url") or f"https://pypi.org/project/{name}/")

        row1: List[types.InlineKeyboardButton] = []
        if pkg_url:
            row1.append(types.InlineKeyboardButton("PyPI", url=pkg_url))
        row2: List[types.InlineKeyboardButton] = []

        proj_urls = info.get("project_urls") or {}
        home_page = _clean_url(info.get("home_page"))

        if isinstance(proj_urls, dict):
            for label, raw_link in proj_urls.items():
                link_url = _clean_url(raw_link)
                if not link_url:
                    continue
                lbl_lower = label.lower()
                if "home" in lbl_lower and len(row1) < 2:
                    row1.append(types.InlineKeyboardButton("Homepage", url=link_url))
                elif any(k in lbl_lower for k in ("source", "repo", "git", "code")) and not any("Repo" in b.text for b in row2):
                    row2.append(types.InlineKeyboardButton("Repository", url=link_url))
                elif any(k in lbl_lower for k in ("doc", "wiki")) and not any("Docs" in b.text for b in row2):
                    row2.append(types.InlineKeyboardButton("Docs", url=link_url))
                elif any(k in lbl_lower for k in ("issue", "bug", "tracker")) and not any("Issues" in b.text for b in row2):
                    row2.append(types.InlineKeyboardButton("Issues", url=link_url))

        if home_page and len(row1) < 2 and not any("Homepage" in b.text for b in row1):
            row1.append(types.InlineKeyboardButton("Homepage", url=home_page))

        buttons: List[List[types.InlineKeyboardButton]] = []
        if row1:
            buttons.append(row1)
        if row2:
            buttons.append(row2[:2])

        # Safely HTML escape all dynamic text
        esc_name = html.escape(str(name))
        esc_ver = html.escape(str(version))
        esc_sum = html.escape(str(summary))
        esc_author = html.escape(str(author))
        esc_license = html.escape(str(license_str))
        esc_pyver = html.escape(str(py_version))

        data_map = {
            "Install": f"<code>pip install {esc_name}</code>",
            "Python": f"<code>{esc_pyver}</code>",
            "License": f"<code>{esc_license}</code>",
            "Author": f"<code>{esc_author}</code>",
        }
        body = util.text.join_map(data_map, parse_mode="html")

        text = (
            f"<blockquote>\n"
            f"<b>PyPI:</b> <a href=\"{pkg_url}\"><b>{esc_name}</b></a> <code>v{esc_ver}</code>\n"
            f"<i>{esc_sum}</i>\n"
            f"{body}\n"
            f"</blockquote>"
        )
        return text, buttons

    # -------------------------------------------------------------------------
    # NPM Lookup
    # -------------------------------------------------------------------------
    async def _get_npm_data(self, query: str) -> Optional[Tuple[str, List[List[types.InlineKeyboardButton]]]]:
        search_url = "https://registry.npmjs.org/-/v1/search"
        resp = await self._http_get(search_url, params={"text": query, "size": 5})

        if resp is None or resp.status_code != 200:
            return None

        data = resp.json()
        objects = data.get("objects", [])
        if not objects:
            return None

        top_pkg = objects[0].get("package", {})
        top_name = top_pkg.get("name", "")
        is_exact = (
            top_name.lower() == query.lower()
            or top_name.lower() == query.lower().replace(" ", "-")
            or len(objects) == 1
        )

        if is_exact:
            name = top_pkg.get("name") or query
            version = top_pkg.get("version") or "unknown"
            desc = top_pkg.get("description") or "No description provided."
            publisher = (
                top_pkg.get("publisher", {}).get("username")
                or top_pkg.get("author", {}).get("name")
                or "Unknown"
            )
            license_str = top_pkg.get("license") or "Not specified"
            links_obj = top_pkg.get("links", {})
            npm_url = _clean_url(links_obj.get("npm") or f"https://www.npmjs.com/package/{name}")
            home_url = _clean_url(links_obj.get("homepage"))
            repo_url = _clean_url(links_obj.get("repository"))
            bugs_url = _clean_url(links_obj.get("bugs"))

            row1: List[types.InlineKeyboardButton] = []
            if npm_url:
                row1.append(types.InlineKeyboardButton("NPM", url=npm_url))
            if home_url:
                row1.append(types.InlineKeyboardButton("Homepage", url=home_url))

            row2: List[types.InlineKeyboardButton] = []
            if repo_url:
                row2.append(types.InlineKeyboardButton("Repository", url=repo_url))
            if bugs_url:
                row2.append(types.InlineKeyboardButton("Issues", url=bugs_url))

            buttons = []
            if row1:
                buttons.append(row1)
            if row2:
                buttons.append(row2[:2])

            esc_name = html.escape(str(name))
            esc_ver = html.escape(str(version))
            esc_desc = html.escape(str(desc))
            esc_pub = html.escape(str(publisher))
            esc_lic = html.escape(str(license_str))

            data_map = {
                "Install": f"<code>npm i {esc_name}</code>",
                "License": f"<code>{esc_lic}</code>",
                "Publisher": f"<code>{esc_pub}</code>",
            }
            body = util.text.join_map(data_map, parse_mode="html")

            text = (
                f"<blockquote>\n"
                f"<b>NPM:</b> <a href=\"{npm_url}\"><b>{esc_name}</b></a> <code>v{esc_ver}</code>\n"
                f"<i>{esc_desc}</i>\n"
                f"{body}\n"
                f"</blockquote>"
            )
            return text, buttons

        # Multiple search results
        esc_q = html.escape(query)
        lines = [f"<b>NPM Search:</b> <code>{esc_q}</code>"]
        buttons_list: List[List[types.InlineKeyboardButton]] = []
        for idx, obj in enumerate(objects, 1):
            pkg = obj.get("package", {})
            p_name = pkg.get("name")
            p_ver = pkg.get("version")
            p_desc = pkg.get("description") or ""
            if len(p_desc) > 60:
                p_desc = p_desc[:57] + "..."
            p_links = pkg.get("links", {})
            p_url = _clean_url(p_links.get("npm") or f"https://www.npmjs.com/package/{p_name}")

            esc_pname = html.escape(str(p_name))
            esc_pver = html.escape(str(p_ver))
            esc_pdesc = html.escape(str(p_desc))
            desc_text = f" — <i>{esc_pdesc}</i>" if esc_pdesc else ""
            lines.append(
                f"<a href=\"{p_url}\"><b>{esc_pname}</b></a> <code>v{esc_pver}</code>{desc_text}"
            )
            if idx <= 3 and p_name and p_url:
                buttons_list.append([types.InlineKeyboardButton(p_name, url=p_url)])

        body = util.text.join_list(lines)
        text = f"<blockquote>\n{body}\n</blockquote>"
        return text, buttons_list

    async def _get_github_data(self, query: str) -> Optional[Tuple[str, List[List[types.InlineKeyboardButton]]]]:
        query = query.strip()
        if not query:
            return None

        is_explicit_search = False
        if query.lower().startswith("search "):
            query = query[7:].strip()
            is_explicit_search = True
        elif query.lower().startswith("find "):
            query = query[5:].strip()
            is_explicit_search = True
        elif query.startswith("-s "):
            query = query[3:].strip()
            is_explicit_search = True

        if not is_explicit_search:
            # Case 1: Specific Repository (owner/repo or URL)
            repo_match = query
            if "github.com/" in repo_match:
                repo_match = repo_match.split("github.com/")[-1].strip("/")

            if "/" in repo_match and len(repo_match.split("/")) == 2:
                owner, repo = repo_match.split("/")
                url = f"https://api.github.com/repos/{owner}/{repo}"
                resp = await self._http_get(url)
                if resp is not None and resp.status_code == 200:
                    d = resp.json()
                    full_name = d.get("full_name") or f"{owner}/{repo}"
                    html_url = _clean_url(d.get("html_url") or f"https://github.com/{full_name}")
                    desc = d.get("description") or "No description provided."
                    stars = d.get("stargazers_count", 0)
                    forks = d.get("forks_count", 0)
                    issues = d.get("open_issues_count", 0)
                    lang = d.get("language") or "None"
                    license_name = (d.get("license") or {}).get("spdx_id") or "Not specified"
                    homepage = _clean_url(d.get("homepage"))

                    row1: List[types.InlineKeyboardButton] = []
                    if html_url:
                        row1.append(types.InlineKeyboardButton("Repository", url=html_url))
                    if homepage:
                        row1.append(types.InlineKeyboardButton("Homepage", url=homepage))

                    row2: List[types.InlineKeyboardButton] = []
                    if issues > 0 and html_url:
                        row2.append(types.InlineKeyboardButton("Issues", url=f"{html_url}/issues"))
                    if html_url:
                        row2.append(types.InlineKeyboardButton("Clone", url=html_url))

                    buttons = []
                    if row1:
                        buttons.append(row1)
                    if row2:
                        buttons.append(row2[:2])

                    esc_fname = html.escape(str(full_name))
                    esc_desc = html.escape(str(desc))
                    esc_lang = html.escape(str(lang))
                    esc_lic = html.escape(str(license_name))

                    data_map = {
                        "Language": f"<code>{esc_lang}</code>",
                        "Stars": f"<code>{stars:,}</code>",
                        "Forks": f"<code>{forks:,}</code>",
                        "Issues": f"<code>{issues:,} open</code>",
                        "License": f"<code>{esc_lic}</code>",
                        "Clone": f"<code>git clone {html_url}.git</code>",
                    }
                    body = util.text.join_map(data_map, parse_mode="html")

                    text = (
                        f"<blockquote>\n"
                        f"<b>GitHub:</b> <a href=\"{html_url}\"><b>{esc_fname}</b></a>\n"
                        f"<i>{esc_desc}</i>\n"
                        f"{body}\n"
                        f"</blockquote>"
                    )
                    return text, buttons

            # Case 2: User profile (single handle)
            if " " not in query and "/" not in query:
                user_url = f"https://api.github.com/users/{urllib.parse.quote(query)}"
                resp = await self._http_get(user_url)
                if resp is not None and resp.status_code == 200:
                    u = resp.json()
                    login = u.get("login")
                    name = u.get("name") or login
                    bio = u.get("bio") or "No bio provided."
                    html_url = _clean_url(u.get("html_url") or f"https://github.com/{login}")
                    public_repos = u.get("public_repos", 0)
                    followers = u.get("followers", 0)
                    following = u.get("following", 0)
                    company = u.get("company") or "None"
                    location = u.get("location") or "None"
                    blog = _clean_url(u.get("blog"))

                    row1: List[types.InlineKeyboardButton] = []
                    if html_url:
                        row1.append(types.InlineKeyboardButton("Profile", url=html_url))
                        row1.append(types.InlineKeyboardButton("Repositories", url=f"{html_url}?tab=repositories"))

                    row2: List[types.InlineKeyboardButton] = []
                    if blog:
                        row2.append(types.InlineKeyboardButton("Website", url=blog))

                    buttons = []
                    if row1:
                        buttons.append(row1)
                    if row2:
                        buttons.append(row2)

                    esc_name = html.escape(str(name))
                    esc_login = html.escape(str(login))
                    esc_bio = html.escape(str(bio))
                    esc_comp = html.escape(str(company))
                    esc_loc = html.escape(str(location))

                    data_map = {
                        "Repos": f"<code>{public_repos:,}</code>",
                        "Followers": f"<code>{followers:,}</code>",
                        "Following": f"<code>{following:,}</code>",
                        "Company": f"<code>{esc_comp}</code>",
                        "Location": f"<code>{esc_loc}</code>",
                    }
                    body = util.text.join_map(data_map, parse_mode="html")

                    text = (
                        f"<blockquote>\n"
                        f"<b>GitHub User:</b> <a href=\"{html_url}\"><b>{esc_name}</b></a> (<code>@{esc_login}</code>)\n"
                        f"<i>{esc_bio}</i>\n"
                        f"{body}\n"
                        f"</blockquote>"
                    )
                    return text, buttons

        # Case 3: Search Repositories
        search_url = "https://api.github.com/search/repositories"
        resp = await self._http_get(search_url, params={"q": query, "per_page": 5})
        if resp is not None and resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                esc_q = html.escape(query)
                lines = [f"<b>GitHub Search:</b> <code>{esc_q}</code>"]
                buttons_list: List[List[types.InlineKeyboardButton]] = []
                for idx, it in enumerate(items, 1):
                    fn = it.get("full_name")
                    stars = it.get("stargazers_count", 0)
                    desc = it.get("description") or ""
                    if len(desc) > 60:
                        desc = desc[:57] + "..."
                    url = _clean_url(it.get("html_url") or f"https://github.com/{fn}")

                    esc_fn = html.escape(str(fn))
                    esc_desc = html.escape(str(desc))
                    desc_text = f" — <i>{esc_desc}</i>" if esc_desc else ""
                    lines.append(
                        f"<a href=\"{url}\"><b>{esc_fn}</b></a> (<code>{stars:,} stars</code>){desc_text}"
                    )
                    if idx <= 3 and fn and url:
                        buttons_list.append([types.InlineKeyboardButton(fn, url=url)])

                body = util.text.join_list(lines)
                text = f"<blockquote>\n{body}\n</blockquote>"
                return text, buttons_list

        return None


    # -------------------------------------------------------------------------
    # Helper Dispatcher (Inline / Fallback)
    # -------------------------------------------------------------------------
    async def _send_with_inline_or_respond(
        self,
        ctx: command.Context,
        inline_query_text: str,
        fallback_text: str,
        fallback_buttons: List[List[types.InlineKeyboardButton]],
    ) -> None:
        if self.bot.helper_initialized and fallback_buttons:
            try:
                bot_user = (
                    getattr(self.bot, "bot_user", None)
                    or self.bot.client_helper.me
                    or await self.bot.client_helper.get_me()
                )
                if bot_user and bot_user.username:
                    if not hasattr(self.bot, "_inline_cache"):
                        self.bot._inline_cache = {}
                    cache_key = uuid.uuid4().hex[:10]
                    self.bot._inline_cache[cache_key] = {
                        "text": fallback_text,
                        "buttons": fallback_buttons,
                    }
                    inline_q = f"pkg_cache {cache_key}"
                    res = await self.bot.client.get_inline_bot_results(
                        bot=bot_user.username,
                        query=inline_q,
                    )
                    if res and res.results:
                        if ctx.msg:
                            try:
                                await ctx.msg.delete()
                            except Exception:
                                pass
                        result_id = res.results[0].id
                        thread_id = getattr(ctx.msg, "message_thread_id", None)
                        if getattr(ctx.chat, "is_forum", False) and thread_id is not None:
                            await self.bot.client.send_inline_bot_result(
                                ctx.msg.chat.id,
                                res.query_id,
                                result_id,
                                message_thread_id=thread_id,
                            )
                        else:
                            await self.bot.client.send_inline_bot_result(
                                ctx.msg.chat.id,
                                res.query_id,
                                result_id,
                            )
                        return
            except Exception as e:
                self.log.debug("Inline dispatch failed, falling back to message edit: %s", e)

        links_parts = []
        for row in fallback_buttons:
            for btn in row:
                if getattr(btn, "url", None):
                    links_parts.append(f"<a href='{btn.url}'>{btn.text}</a>")
        links_suffix = f"\n    • <b>Links:</b> " + " — ".join(links_parts) if links_parts else ""

        if "</blockquote>" in fallback_text:
            text = fallback_text.replace("</blockquote>", f"{links_suffix}\n</blockquote>")
        else:
            text = fallback_text + links_suffix

        await ctx.respond(
            text,
            parse_mode=ParseMode.HTML,
            link_preview_options=types.LinkPreviewOptions(is_disabled=True),
        )

    # -------------------------------------------------------------------------
    # Commands
    # -------------------------------------------------------------------------
    @command.desc("Search or inspect Python packages from PyPI")
    @command.alias("pypisearch", "pypifind", "pip")
    @command.usage("[package name or search query]")
    async def cmd_pypi(self, ctx: command.Context) -> Optional[str]:
        query = ctx.input.strip()
        if not query:
            return "<i>Please provide a package name to search on PyPI.</i>"

        result = await self._get_pypi_data(query)
        if not result:
            return f"<i>No PyPI package found matching</i> <code>{html.escape(query)}</code>."

        text, buttons = result
        await self._send_with_inline_or_respond(ctx, f"pypi {query}", text, buttons)

    @command.desc("Search or inspect Node.js packages from NPM")
    @command.alias("npmsearch", "npmfind", "npmjs")
    @command.usage("[package name or search query]")
    async def cmd_npm(self, ctx: command.Context) -> Optional[str]:
        query = ctx.input.strip()
        if not query:
            return "<i>Please provide an NPM package name or search query.</i>"

        result = await self._get_npm_data(query)
        if not result:
            return f"<i>No NPM package found matching</i> <code>{html.escape(query)}</code>."

        text, buttons = result
        await self._send_with_inline_or_respond(ctx, f"npm {query}", text, buttons)

    @command.desc("Lookup GitHub repository, user profile, or search repositories")
    @command.alias("git", "gh", "repo")
    @command.usage("[user/repo | username | search term]")
    async def cmd_github(self, ctx: command.Context) -> Optional[str]:
        query = ctx.input.strip()
        if not query:
            return "<i>Please provide a GitHub repo (owner/repo), user, or search query.</i>"

        result = await self._get_github_data(query)
        if not result:
            return f"<i>No GitHub results found for</i> <code>{html.escape(query)}</code>."

        text, buttons = result
        await self._send_with_inline_or_respond(ctx, f"gh {query}", text, buttons)

    # -------------------------------------------------------------------------
    # Inline Query Handler
    # -------------------------------------------------------------------------
    async def on_inline_query(self, query: types.InlineQuery) -> None:
        q = (query.query or "").strip()
        if not q:
            return

        q_lower = q.lower()
        results: List[types.InlineQueryResultArticle] = []

        try:
            if q_lower.startswith("pypi ") or q_lower.startswith("pip "):
                pkg_name = q.split(maxsplit=1)[1].strip()
                data = await self._get_pypi_data(pkg_name)
                if data:
                    text, buttons = data
                    results.append(
                        types.InlineQueryResultArticle(
                            id=str(uuid.uuid4()),
                            title=f"PyPI: {pkg_name}",
                            input_message_content=types.InputTextMessageContent(
                                text,
                                parse_mode=ParseMode.HTML,
                                link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                            ),
                            description=f"View Python package {pkg_name} on PyPI",
                            reply_markup=types.InlineKeyboardMarkup(buttons) if buttons else None,
                        )
                    )

            elif q_lower.startswith("npm ") or q_lower.startswith("npmjs "):
                pkg_name = q.split(maxsplit=1)[1].strip()
                data = await self._get_npm_data(pkg_name)
                if data:
                    text, buttons = data
                    results.append(
                        types.InlineQueryResultArticle(
                            id=str(uuid.uuid4()),
                            title=f"NPM: {pkg_name}",
                            input_message_content=types.InputTextMessageContent(
                                text,
                                parse_mode=ParseMode.HTML,
                                link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                            ),
                            description=f"View Node package {pkg_name} on NPM",
                            reply_markup=types.InlineKeyboardMarkup(buttons) if buttons else None,
                        )
                    )

            elif q_lower.startswith("gh ") or q_lower.startswith("git ") or q_lower.startswith("github "):
                gh_query = q.split(maxsplit=1)[1].strip()
                data = await self._get_github_data(gh_query)
                if data:
                    text, buttons = data
                    results.append(
                        types.InlineQueryResultArticle(
                            id=str(uuid.uuid4()),
                            title=f"GitHub: {gh_query}",
                            input_message_content=types.InputTextMessageContent(
                                text,
                                parse_mode=ParseMode.HTML,
                                link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                            ),
                            description=f"View GitHub info for {gh_query}",
                            reply_markup=types.InlineKeyboardMarkup(buttons) if buttons else None,
                        )
                    )

            if results:
                await query.answer(results=results, cache_time=10)
        except Exception as e:
            self.log.error("Inline query answer error: %s", e)

import urllib.parse
from typing import Any, ClassVar, Dict, List, Optional, Tuple

import httpx

from caligo import command, module


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
        try:
            if http is not None:
                return await http.get(url, params=params, headers=headers, timeout=timeout)
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
                return await client.get(url, params=params, headers=headers)
        except Exception as e:
            self.log.debug("HTTP GET error for %s: %s", url, e)
            return None

    @command.desc("Search or get info about Python packages on PyPI")
    @command.alias("pypisearch", "pypifind", "pip")
    @command.usage("[package name or search query]")
    async def cmd_pypi(self, ctx: command.Context) -> str:
        query = ctx.input.strip()
        if not query:
            return "__Please provide a package name to search on PyPI.__"

        # Generate candidate names to check against PyPI JSON API
        raw = query.lower()
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

        # Deduplicate while preserving order
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
            return f'__No PyPI package found matching "`{query}`".__'

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
        if len(license_str) > 40:
            license_str = license_str[:37] + "..."
        py_version = info.get("requires_python") or "Any"
        pkg_url = info.get("package_url") or f"https://pypi.org/project/{name}/"

        # Collect project links
        links: List[str] = [f"[PyPI]({pkg_url})"]
        proj_urls = info.get("project_urls") or {}
        if isinstance(proj_urls, dict):
            for label, link_url in proj_urls.items():
                if not link_url:
                    continue
                lbl_lower = label.lower()
                if any(
                    k in lbl_lower
                    for k in ("home", "doc", "source", "repo", "git", "issue", "bug")
                ):
                    links.append(f"[{label}]({link_url})")

        home_page = info.get("home_page")
        if home_page and not any("home" in l.lower() for l in links):
            links.append(f"[Homepage]({home_page})")

        links_line = " • ".join(links[:5])

        return (
            f"📦 **[{name}]({pkg_url})** `v{version}`\n"
            f"_{summary}_\n\n"
            f"• **Install:** `pip install {name}`\n"
            f"• **Python:** `{py_version}`\n"
            f"• **License:** `{license_str}`\n"
            f"• **Author:** `{author}`\n"
            f"• **Links:** {links_line}"
        )

    @command.desc("Search or get info about Node.js packages on NPM")
    @command.alias("npmsearch", "npmfind", "npmjs")
    @command.usage("[package name or search query]")
    async def cmd_npm(self, ctx: command.Context) -> str:
        query = ctx.input.strip()
        if not query:
            return "__Please provide an NPM package name or search query.__"

        search_url = "https://registry.npmjs.org/-/v1/search"
        resp = await self._http_get(search_url, params={"text": query, "size": 5})

        if resp is None or resp.status_code != 200:
            return f"__Failed to query NPM registry for `{query}`.__"

        data = resp.json()
        objects = data.get("objects", [])

        if not objects:
            return f'__No NPM packages found matching "`{query}`".__'

        top_pkg = objects[0].get("package", {})
        top_name = top_pkg.get("name", "")
        is_exact_match = (
            top_name.lower() == query.lower()
            or top_name.lower() == query.lower().replace(" ", "-")
            or len(objects) == 1
        )

        if is_exact_match:
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
            npm_url = links_obj.get("npm") or f"https://www.npmjs.com/package/{name}"

            links = [f"[NPM]({npm_url})"]
            if links_obj.get("homepage"):
                links.append(f"[Homepage]({links_obj['homepage']})")
            if links_obj.get("repository"):
                links.append(f"[Repository]({links_obj['repository']})")
            if links_obj.get("bugs"):
                links.append(f"[Issues]({links_obj['bugs']})")

            links_line = " • ".join(links[:4])

            return (
                f"📦 **[{name}]({npm_url})** `v{version}`\n"
                f"_{desc}_\n\n"
                f"• **Install:** `npm i {name}`\n"
                f"• **License:** `{license_str}`\n"
                f"• **Publisher:** `{publisher}`\n"
                f"• **Links:** {links_line}"
            )

        # Multiple search results list
        lines = [f"🔍 **NPM Search Results for** `{query}`:\n"]
        for idx, obj in enumerate(objects, 1):
            pkg = obj.get("package", {})
            p_name = pkg.get("name")
            p_ver = pkg.get("version")
            p_desc = pkg.get("description") or ""
            p_links = pkg.get("links", {})
            p_url = p_links.get("npm") or f"https://www.npmjs.com/package/{p_name}"
            desc_text = f"_{p_desc}_\n   " if p_desc else ""
            lines.append(
                f"{idx}. **[{p_name}]({p_url})** `v{p_ver}`\n"
                f"   {desc_text}`npm i {p_name}`"
            )
        lines.append(f"\n__Tip: Use `{self.bot.prefix}npm <exact_name>` for full details.__")
        return "\n\n".join(lines)

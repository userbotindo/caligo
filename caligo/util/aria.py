import aiohttp

from . import system


async def initialize(http: aiohttp.ClientSession) -> None:
    """Setup aria2p/c"""
    link = "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt"

    async with http.get(link) as resp:
        trackers_list: str = await resp.text()
        trackers: str = "[" + trackers_list.replace('\n\n', ',') + "]"

    await system.run_command(
        "aria2c",
        "--enable-rpc",
        "--rpc-listen-all=false",
        "--rpc-listen-port=6800",
        "--max-connection-per-server=10",
        "--rpc-max-request-size=1024M",
        "--seed-time=120",
        "--max-upload-limit=5K",
        "--max-concurrent-downloads=5",
        "--min-split-size=10M",
        "--follow-torrent=mem",
        "--split=10",
        f"--bt-tracker={trackers}",
        "--daemon=true",
        "--allow-overwrite=true",
        timeout=10
    )

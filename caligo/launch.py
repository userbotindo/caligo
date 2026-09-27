import asyncio
import logging
import os
import sys
from typing import Any, MutableMapping

from .core import Caligo

log = logging.getLogger("Launch")


def setup_dns() -> None:
    try:
        import dns.resolver

        try:
            import dns.asyncresolver
        except ImportError:
            dns.asyncresolver = None  # type: ignore

        if not os.path.exists("/etc/resolv.conf"):
            prefix_resolv = os.path.join(
                os.environ.get("PREFIX", "/data/data/com.termux/files/usr"),
                "etc",
                "resolv.conf",
            )
            if os.path.exists(prefix_resolv):
                dns.resolver.default_resolver = dns.resolver.Resolver(
                    filename=prefix_resolv
                )
                if dns.asyncresolver is not None:
                    dns.asyncresolver.default_resolver = dns.asyncresolver.Resolver(
                        filename=prefix_resolv
                    )
            else:
                r = dns.resolver.Resolver(configure=False)
                r.nameservers = ["8.8.8.8", "1.1.1.1"]
                dns.resolver.default_resolver = r
                if dns.asyncresolver is not None:
                    ar = dns.asyncresolver.Resolver(configure=False)
                    ar.nameservers = ["8.8.8.8", "1.1.1.1"]
                    dns.asyncresolver.default_resolver = ar
    except Exception:
        pass


setup_dns()


def main(config: MutableMapping[str, Any]) -> None:
    """Main entry point for the default bot launcher."""

    setup_dns()

    if sys.platform == "win32":
        policy = asyncio.WindowsProactorEventLoopPolicy()
        asyncio.set_event_loop_policy(policy)
    else:
        try:
            import uvloop
        except ImportError:
            pass
        else:
            uvloop.install()
            log.info("Using uvloop event loop")

    log.info("Initializing bot")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(Caligo.create_and_run(config, loop=loop))
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        try:
            tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in tasks:
                task.cancel()
            if tasks:
                loop.run_until_complete(
                    asyncio.gather(*tasks, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        finally:
            asyncio.set_event_loop(None)
            loop.close()

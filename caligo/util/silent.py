import io
import sys
from contextlib import asynccontextmanager


@asynccontextmanager
async def silent() -> None:
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = old_stdout

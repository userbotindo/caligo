import time
from datetime import timedelta
from typing import Union


def usec() -> int:
    """Returns the current time in microseconds since the Unix epoch."""

    return int(time.time() * 1000000)


def msec() -> int:
    """Returns the current time in milliseconds since the Unix epoch."""

    return int(usec() / 1000)


def sec() -> int:
    """Returns the current time in seconds since the Unix epoch."""

    return int(time.time())


def format_duration_us(t_us: Union[int, float]) -> str:
    """Formats the given microsecond duration as a string."""

    t_us = int(t_us)
    if t_us < 1000:
        return f"{t_us} μs"

    t_ms = t_us // 1000
    if t_ms < 1000:
        return f"{t_ms} ms"

    t_s = t_ms // 1000
    if t_s < 60:
        return f"{t_s} sec"

    t_m = t_s // 60
    if t_m < 60:
        return f"{t_m}m {t_s % 60}s"

    t_h = t_m // 60
    if t_h < 24:
        return f"{t_h}h {t_m % 60}m"

    t_d = t_h // 24
    return f"{t_d}d {t_h % 24}h"


def format_duration_td(value: timedelta, precision: int = 0) -> str:
    pieces = []

    if value.days:
        pieces.append(f"{value.days}d")

    seconds = value.seconds

    if seconds >= 3600:
        hours, seconds = divmod(seconds, 3600)
        pieces.append(f"{hours}h")

    if seconds >= 60:
        minutes, seconds = divmod(seconds, 60)
        pieces.append(f"{minutes}m")

    if seconds > 0 or not pieces:
        pieces.append(f"{seconds}s")

    if precision == 0:
        return "".join(pieces)

    return "".join(pieces[:precision])

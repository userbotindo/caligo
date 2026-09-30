import re
import time
from datetime import timedelta
from typing import Optional, Tuple, Union


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


def parse_duration(text: str) -> Optional[timedelta]:
    """Parses duration string (e.g. '10s', '30m', '2h', '1d', '2w', '1d12h') into timedelta."""
    tokens = re.findall(r"(\d+)\s*([smhdw])", text, re.IGNORECASE)
    if not tokens:
        return None

    remainder = re.sub(r"(\d+)\s*([smhdw])", "", text, flags=re.IGNORECASE).strip()
    if remainder:
        return None

    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    total = sum(int(val) * multipliers[unit.lower()] for val, unit in tokens)
    return timedelta(seconds=total)


def extract_duration_and_reason(
    rest: Optional[str],
) -> Tuple[Optional[timedelta], Optional[str]]:
    """Extracts a leading duration (if any) and remaining text as reason."""
    if not rest:
        return None, None

    parts = rest.split(maxsplit=1)
    dur = parse_duration(parts[0])
    if dur is not None:
        reason = parts[1].strip() if len(parts) > 1 else None
        return dur, reason

    return None, rest


USEC_PER_HOUR = 60 * 60 * 1000000
USEC_PER_DAY = USEC_PER_HOUR * 24


def calc_pct(num1: int, num2: int) -> str:
    """Calculates percentage string representation without trailing zeros."""
    if not num2:
        return "0"

    return "{:.1f}".format((num1 / num2) * 100).rstrip("0").rstrip(".")


def calc_per_hour(stat: int, uptime_us: int) -> str:
    """Calculates hourly rate string representation given total stat and uptime in microseconds."""
    up_hr = max(1, uptime_us) / USEC_PER_HOUR
    val = stat / up_hr
    if val >= 1000:
        return f"{val:,.1f}".rstrip("0").rstrip(".")
    return "{:.1f}".format(val).rstrip("0").rstrip(".")


def calc_per_day(stat: int, uptime_us: int) -> str:
    """Calculates daily rate string representation given total stat and uptime in microseconds."""
    up_day = max(1, uptime_us) / USEC_PER_DAY
    val = stat / up_day
    if val >= 1000:
        return f"{val:,.1f}".rstrip("0").rstrip(".")
    return "{:.1f}".format(val).rstrip("0").rstrip(".")


calc_ph = calc_per_hour
calc_pd = calc_per_day


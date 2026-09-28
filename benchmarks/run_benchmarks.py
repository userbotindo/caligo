#!/usr/bin/env python3
"""Reproducible benchmark suite for Caligo hot paths."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asyncio
import cProfile
import pstats
import time
import tracemalloc
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from caligo.core.command_dispatcher import CommandDispatcher
from caligo.core.database.storage import PersistentStorage
from caligo.core.telegram_bot import TelegramBot
from caligo.modules.stats import _calc_pct, _calc_pd, _calc_ph
from caligo.util import misc, text, tg, time as util_time


def benchmark_storage_accessor(iterations=100):
    mock_db = MagicMock()
    mock_session = MagicMock()
    mock_db.__getitem__.return_value = mock_session
    mock_session.find_one = AsyncMock(return_value={"dc_id": 2, "api_id": 12345})
    mock_session.update_one = AsyncMock()

    storage = PersistentStorage(mock_db)

    async def run():
        for _ in range(iterations):
            await storage.dc_id()
            await storage.api_id()
            await storage.dc_id(4)

    t0 = time.perf_counter()
    asyncio.run(run())
    t1 = time.perf_counter()
    return (t1 - t0) / iterations


def benchmark_command_predicate(iterations=1000):
    dispatcher = CommandDispatcher()
    dispatcher.prefix = "."
    dispatcher.commands = {
        "help": MagicMock(filters=None),
        "ping": MagicMock(filters=None),
        "stats": MagicMock(filters=None),
    }
    predicate_filter = dispatcher.command_predicate()

    client = MagicMock()
    msg_cmd = MagicMock()
    msg_cmd.via_bot = False
    msg_cmd.text = ".help test argument with multiple words"

    msg_non_cmd = MagicMock()
    msg_non_cmd.via_bot = False
    msg_non_cmd.text = "Just a regular long chat message that is not a command at all." * 10

    async def run():
        for _ in range(iterations):
            await predicate_filter(client, msg_cmd)
            await predicate_filter(client, msg_non_cmd)

    t0 = time.perf_counter()
    asyncio.run(run())
    t1 = time.perf_counter()
    return (t1 - t0) / (iterations * 2)


def benchmark_redact_message(iterations=5000):
    class DummyBot(TelegramBot):
        def __init__(self):
            self.config = {
                "telegram": {
                    "api_id": 9876543,
                    "api_hash": "abcdef1234567890abcdef1234567890",
                    "helper": {"token": "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"},
                },
                "bot": {"db_uri": "mongodb+srv://admin:pass@cluster.mongodb.net/test"},
            }

    bot = DummyBot()
    sample_text = (
        "Server startup finished with api_id: 9876543 and api_hash: "
        "abcdef1234567890abcdef1234567890, connected to database at "
        "mongodb+srv://admin:pass@cluster.mongodb.net/test using helper "
        "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ. Everything is working normally."
    )

    t0 = time.perf_counter()
    for _ in range(iterations):
        bot.redact_message(sample_text)
    t1 = time.perf_counter()
    return (t1 - t0) / iterations


def benchmark_format_progress(iterations=2000):
    eta = timedelta(seconds=125)
    t0 = time.perf_counter()
    for _ in range(iterations):
        tg.format_progress(
            file_name="very_long_file_name_video_benchmark.mkv",
            status="Uploading",
            percent=0.456,
            current=47852960,
            total=104857600,
            speed=2097152.0,
            eta=eta,
            style="bullet",
        )
    t1 = time.perf_counter()
    return (t1 - t0) / iterations


def benchmark_time_formatting(iterations=5000):
    td = timedelta(days=2, hours=5, minutes=34, seconds=42)
    usec_val = 192882000000

    t0 = time.perf_counter()
    for _ in range(iterations):
        util_time.format_duration_td(td, precision=2)
        util_time.format_duration_us(usec_val)
    t1 = time.perf_counter()
    return (t1 - t0) / iterations


def benchmark_text_formatting(iterations=2000):
    data = {
        "Version": "1.0.0",
        "Python": "3.14.6",
        "Kurigram": "2.2.26",
        "Commands loaded": 42,
        "Modules loaded": 8,
        "Listeners loaded": 15,
        "Events activated": 4,
        "Chats": 128,
    }
    sample_emoji_text = "Checking text with some emojis 🔥🚀 and normal characters." * 5

    t0 = time.perf_counter()
    for _ in range(iterations):
        text.join_map(data, heading="Caligo Benchmark", parse_mode="html")
        text.has_emoji(sample_emoji_text)
    t1 = time.perf_counter()
    return (t1 - t0) / iterations


def run_all_benchmarks():
    print("=" * 65)
    print("CALIGO PERFORMANCE BENCHMARK SUITE")
    print("=" * 65)

    tracemalloc.start()
    pr = cProfile.Profile()
    pr.enable()

    benchmarks = [
        ("Storage Accessor (per 3 ops)", benchmark_storage_accessor),
        ("Command Predicate (per call)", benchmark_command_predicate),
        ("Message Redaction (per call)", benchmark_redact_message),
        ("Format Progress (per call)", benchmark_format_progress),
        ("Time Formatting (per 2 ops)", benchmark_time_formatting),
        ("Text Formatting & Emoji (per call)", benchmark_text_formatting),
    ]

    results = {}
    for name, bench_fn in benchmarks:
        print(f"Running {name}...", end=" ", flush=True)
        avg_time = bench_fn()
        us = avg_time * 1e6
        ms = avg_time * 1e3
        if ms >= 1.0:
            formatted = f"{ms:.3f} ms"
        else:
            formatted = f"{us:.2f} µs"
        print(f"DONE -> {formatted}")
        results[name] = (avg_time, formatted)

    pr.disable()
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print("\n" + "=" * 65)
    print(f"Memory: Current = {current_mem / 1024:.2f} KiB, Peak = {peak_mem / 1024:.2f} KiB")
    print("=" * 65)

    # cProfile Top Functions
    s = pstats.Stats(pr)
    s.strip_dirs()
    s.sort_stats("cumulative")
    print("\nTop 15 Functions by Cumulative Time (cProfile):")
    s.print_stats(15)

    return results


if __name__ == "__main__":
    run_all_benchmarks()

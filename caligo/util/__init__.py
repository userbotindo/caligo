from . import (
    aria2,
    async_helpers,
    config,
    db,
    error,
    file,
    git,
    image,
    misc,
    system,
    text,
    tg,
    time,
    version,
)

File = file.File
TelegramConfig = config.TelegramConfig()

run_sync = async_helpers.run_sync

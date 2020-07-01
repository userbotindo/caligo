# Copyright (C) 2020 Adek Maulana
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os

from distutils.util import strtobool as sb

from logging import basicConfig, getLogger, INFO, DEBUG, StreamHandler
from logging.handlers import RotatingFileHandler


if not os.path.isdir(".logs"):
    os.mkdir(".logs")

CONSOLE_LOGGER_VERBOSE = sb(os.environ.get("CONSOLE_LOGGER_VERBOSE", "False"))

if CONSOLE_LOGGER_VERBOSE:
    basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt='%d-%b-%y %H:%M:%S',
        level=DEBUG,
    )
else:
    basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt='%d-%b-%y %H:%M:%S',
        level=INFO,
        handlers=[
            RotatingFileHandler(
                ".logs/bish.log", maxBytes=(20480), backupCount=9),
            StreamHandler()
        ]
    )

LOGS = getLogger(__name__)

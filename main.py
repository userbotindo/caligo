#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
from git import Repo

if __name__ == '__main__':
    REPO = os.environ.get("REPO", "adekmaulana/caligo")
    HOME = os.environ.get("HOME")

    if not os.listdir(HOME):
        Repo.clone_from(f"https://github.com/{REPO}.git", HOME)

    sys.exit(os.execv(sys.executable, (sys.executable, "-m", "caligo")))  # skipcq: BAN-B606

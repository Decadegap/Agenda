# -*- coding: utf-8 -*-
import os
import sys
import shutil

os.environ["APPDATA"] = os.environ.get("APPDATA", os.path.expanduser("~"))
base = os.path.abspath(os.path.dirname(__file__))
if base not in sys.path:
    sys.path.insert(0, base)

from PyInstaller.__main__ import run

run([
    os.path.join(base, "main.py"),
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "Agenda",
    "--distpath", os.path.join(base, "dist"),
    "--workpath", os.path.join(base, "build"),
    "--specpath", os.path.join(base, "build"),
])

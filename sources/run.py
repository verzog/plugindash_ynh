#!/usr/bin/env python3
"""Entry point used by systemd and the YunoHost scripts.

Run with `python3 -I run.py ...`: isolated mode ignores PYTHONPATH and the
user's site-packages, so only this folder's code and the standard library load.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from plugindash.__main__ import main  # noqa: E402

sys.exit(main())

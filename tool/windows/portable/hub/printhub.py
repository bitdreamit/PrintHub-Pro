#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Back-compat shim: 'python printhub.py ...' now runs AdvPrint Pro.

Since v2.6.0 the product is AdvPrint Pro (Advanced Printer) by
Bit Dream IT - Innovative Healthcare Solutions. This shim keeps old
bookmarks, scripts, scheduled tasks and muscle memory working: every
command is forwarded to advprint.py unchanged.
"""
import os
import runpy
import sys

sys.argv[0] = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "advprint.py")
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as e:  # advprint.py uses sys.exit codes
    raise e

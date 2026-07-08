"""Launcher: startet LocalFlow unabhaengig vom Arbeitsverzeichnis."""

import os
import sys

if sys.platform not in ("win32", "darwin"):
    sys.exit("LocalFlow supports Windows and (experimentally) macOS - "
             f"no backend for {sys.platform!r}. See PORTING.md.")
if sys.platform == "darwin":
    print("NOTE: the macOS backend is EXPERIMENTAL and untested on real "
          "hardware (no overlay yet, feedback via sounds) - see PORTING.md.")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from localflow.main import main

if __name__ == "__main__":
    main()

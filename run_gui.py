"""
Launch the FFXIV Translation Tool GUI.
Run from the project root:   python run_gui.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from interpresona.gui import main as main_advanced
from interpresona.simple_gui import main as main_simple

if __name__ == "__main__":
    if "--simple" in sys.argv or "-s" in sys.argv:
        main_simple()
    else:
        main_advanced()

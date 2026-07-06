"""
Launch the FFXIV Translation Tool GUI.
Run from the project root:   python run_gui.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from interpresona.gui import main

if __name__ == "__main__":
    main()

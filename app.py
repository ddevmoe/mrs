import sys
from pathlib import Path

# src/ layout: make the `mrs` package importable when run as a bare `python app.py`
# without installing the project or exporting PYTHONPATH.
SOURCE_DIRECTORY = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SOURCE_DIRECTORY))

from mrs.cli import main

if __name__ == "__main__":
    main()

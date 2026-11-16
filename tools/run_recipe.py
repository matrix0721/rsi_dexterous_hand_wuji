"""The original recipe/repair interface, using this project's bundled drivers."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wujiimagine.recipe_cli import main

if __name__ == "__main__":
    raise SystemExit(main())

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if SOURCE_ROOT.exists():
    sys.path.insert(0, str(SOURCE_ROOT))
from review_fix_loop.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["gate", *sys.argv[1:]]))

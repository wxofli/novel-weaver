"""Run the local source tree without installing or downloading dependencies."""
from pathlib import Path
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    # Project sources win; .deps is an optional, explicitly prepared local cache.
    for directory in (root / ".deps", root / "src"):
        if directory.is_dir():
            sys.path.insert(0, str(directory))
    from novel_weaver.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())

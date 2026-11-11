"""Select only the requested version's changelog section for a GitHub release."""
from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def release_notes(changelog, version):
    sections = re.split(r"(?m)^## ", changelog)
    matching = [section for section in sections[1:]
                if re.match(re.escape(version) + r"(?:\s|$)", section)]
    if len(matching) != 1 or "\n" not in matching[0]:
        raise ValueError(f"Expected exactly one changelog section for {version}")
    return "## " + matching[0].strip() + "\n"


if __name__ == "__main__":
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    print(release_notes((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version), end="")

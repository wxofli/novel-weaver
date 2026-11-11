"""Build the Codex plugin ZIP from an explicit release allowlist."""
from pathlib import Path
import ast
import json
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ".codex-plugin/plugin.json"
FILES = (MANIFEST, ".mcp.json", "pyproject.toml", "uv.lock", ".python-version", "README.md", "README.en.md",
         "LICENSE", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
         "THIRD_PARTY_NOTICES.md", ".agents/plugins/marketplace.json")
DIRECTORIES = ("src", "skills", "hooks", "scripts", "docs", "examples")


def version(root=ROOT):
    if (root / "plugin.json").exists():
        raise ValueError("A root plugin.json takes precedence over the Codex manifest and can prevent hooks from loading")
    value = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    plugin = json.loads((root / MANIFEST).read_text(encoding="utf-8"))["version"]
    tree = ast.parse((root / "src/novel_weaver/__init__.py").read_text(encoding="utf-8"))
    runtime = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "__version__" for t in n.targets))
    if not value == plugin == runtime:
        raise ValueError(f"Version mismatch: pyproject={value}, plugin={plugin}, runtime={runtime}")
    return value


def release_file(path):
    return not (set(path.parts) & {"__pycache__", ".novel", ".venv", ".cache", "books", "作品"}
                or path.name.startswith(".env") or path.suffix in {".pyc", ".db", ".sqlite", ".sqlite3", ".key", ".pem"}
                or ".sqlite-" in path.name or "credentials" in path.name.lower() or "secrets" in path.name.lower())


def package(destination=None, *, root=ROOT):
    release_version = version(root)
    output = Path(destination) if destination else root / "dist" / f"novel-weaver-{release_version}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    candidates = [root / filename for filename in FILES]
    for directory in DIRECTORIES:
        candidates.extend(path for path in (root / directory).rglob("*") if path.is_file())
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(candidates):
            relative = path.relative_to(root)
            if release_file(relative):
                archive.write(path, relative.as_posix())
    return output


if __name__ == "__main__":
    print(package())

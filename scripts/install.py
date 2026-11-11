"""Install Novel Weaver using Codex's plugin manager; Python standard library only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = "wxofli-novels"
SELECTOR = f"novel-weaver@{MARKETPLACE}"
REPOSITORY = "wxofli/novel-weaver"


class InstallError(RuntimeError):
    pass


def find_command(name):
    candidates = [name + ".cmd", name + ".exe", name] if os.name == "nt" else [name]
    for candidate in candidates:
        found = shutil.which(candidate)
        if found and not found.lower().endswith(".ps1"):
            return found
    raise InstallError(f"Required command '{name}' was not found on PATH. Install it, then retry.")


def run(command, *, json_output=False):
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise InstallError(f"Command failed ({result.returncode}): {command!r}\n{result.stderr.strip() or result.stdout.strip()}")
    if json_output:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise InstallError(f"Command did not return valid JSON: {command!r}") from exc
    return result.stdout


def check_existing_source(source, ref):
    """Protect a user's same-name marketplace from being silently repointed."""
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    config = home / "config.toml"
    if not config.exists():
        return
    try:
        entry = tomllib.loads(config.read_text(encoding="utf-8")).get("marketplaces", {}).get(MARKETPLACE)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise InstallError(f"Cannot safely read marketplace configuration: {config}") from exc
    if not entry:
        return
    existing = entry.get("source", "")
    if ref is None:
        # Windows Codex stores verbatim paths (\\?\ prefix).
        existing = existing.removeprefix("\\\\?\\")
        matches = entry.get("source_type") == "local" and Path(existing).resolve() == Path(source).resolve()
    else:
        normalized = existing.removesuffix(".git").removesuffix("/")
        matches = (normalized in {REPOSITORY, "https://github.com/" + REPOSITORY}
                   and entry.get("ref") == ref)
    if not matches:
        raise InstallError(f"Marketplace '{MARKETPLACE}' already uses a different source/ref. "
                           "Review it with 'codex plugin marketplace list --json'; no entry was overwritten.")


def install(*, local=None, dry_run=False):
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    source = str(Path(local).resolve()) if local else REPOSITORY
    ref = None if local else "v" + version
    if local and not (Path(source) / ".agents/plugins/marketplace.json").is_file():
        raise InstallError(f"Local source lacks .agents/plugins/marketplace.json: {source}")
    codex, uv = find_command("codex"), find_command("uv")
    check_existing_source(source, ref)
    add_marketplace = [codex, "plugin", "marketplace", "add", source]
    if ref:
        add_marketplace += ["--ref", ref]
    add_marketplace += ["--json"]
    add_plugin = [codex, "plugin", "add", SELECTOR, "--json"]
    if dry_run:
        return {"dryRun": True, "commands": [add_marketplace, add_plugin],
                "next": "Read installedPath from plugin add JSON; uv sync --locked --project installedPath; "
                        "uv run --locked --no-sync --project installedPath novelctl --help"}
    marketplace = run(add_marketplace, json_output=True)
    if not isinstance(marketplace, dict) or marketplace.get("marketplaceName") != MARKETPLACE:
        raise InstallError("Unexpected marketplace registration response; dependency setup was not attempted.")
    plugin = run(add_plugin, json_output=True)
    if not isinstance(plugin, dict) or not isinstance(plugin.get("installedPath"), str):
        raise InstallError("Plugin response lacks installedPath; dependency setup was not attempted.")
    installed = Path(plugin["installedPath"])
    if not installed.is_absolute() or not (installed / "pyproject.toml").is_file() or not (installed / "uv.lock").is_file():
        raise InstallError(f"Invalid installedPath returned by Codex: {installed}")
    installed_version = tomllib.loads((installed / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if installed_version != version:
        raise InstallError(f"Installed version {installed_version} differs from installer version {version}; review the existing plugin.")
    run([uv, "sync", "--locked", "--project", str(installed)])
    run([uv, "run", "--locked", "--no-sync", "--project", str(installed), "novelctl", "--help"])
    return {"installedPath": str(installed), "version": version,
            "next": "Restart Codex. Review and trust this plugin's hooks in Settings > Hooks (CLI: /hooks)."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", type=Path, help="Use an extracted ZIP or local repository root")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without changing config or installing dependencies")
    args = parser.parse_args(argv)
    try:
        result = install(local=args.local, dry_run=args.dry_run)
    except (InstallError, OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

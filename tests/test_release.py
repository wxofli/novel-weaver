"""Release boundaries: version agreement, clean payloads and safe installer failures."""
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_notes_select_exact_version():
    notes = script("release_notes").release_notes
    text = "# Changes\n\n## Unreleased\nFuture\n\n## 0.1.1\nNew\n\n## 0.1.0 Preview\nInitial\n\n## 0.0.1\nOld\n"
    assert notes(text, "0.1.0") == "## 0.1.0 Preview\nInitial\n"
    with pytest.raises(ValueError, match="exactly one"):
        notes(text, "0.1.9")
    with pytest.raises(ValueError, match="exactly one"):
        notes(text + "\n## 0.1.0\nDuplicate", "0.1.0")


def test_package_contents_and_secret_exclusions(tmp_path):
    module = script("package")
    root = tmp_path / "source"
    import shutil
    for filename in module.FILES:
        target = root / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / filename, target)
    for directory in module.DIRECTORIES:
        (root / directory).mkdir(exist_ok=True)
    target = root / "src/novel_weaver/__init__.py"
    target.parent.mkdir()
    target.write_text('__version__ = "0.1.0"', encoding="utf-8")
    for filename in ("docs/.env", "src/credentials.json", "examples/private.sqlite", "scripts/__pycache__/x.pyc", "docs/.novel/project.json"):
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private", encoding="utf-8")
    archive = module.package(tmp_path / "plugin.zip", root=root)
    with zipfile.ZipFile(archive) as payload:
        names = payload.namelist()
    assert set(module.FILES) <= set(names)
    assert "src/novel_weaver/__init__.py" in names
    assert not any("private" in name or "credentials" in name or ".env" in name or ".novel" in name or "__pycache__" in name for name in names)
    (root / "plugin.json").write_text('{"version":"99.0.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Version mismatch"):
        module.package(tmp_path / "mismatch.zip", root=root)


@pytest.fixture
def installer(monkeypatch, tmp_path):
    module = script("install")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setattr(module, "find_command", lambda name: name)
    installed = tmp_path / "actual installed directory"
    installed.mkdir()
    (installed / "pyproject.toml").write_text('[project]\nversion="0.1.0"\n', encoding="utf-8")
    (installed / "uv.lock").touch()
    calls = []

    def run(command, *, json_output=False):
        calls.append(command)
        if command[1:4] == ["plugin", "marketplace", "add"]:
            return {"marketplaceName": module.MARKETPLACE, "alreadyAdded": len(calls) > 4}
        if command[1:3] == ["plugin", "add"]:
            return {"installedPath": str(installed)}
        return "ok"

    monkeypatch.setattr(module, "run", run)
    return module, installed, calls


def test_installer_uses_actual_path_and_repeats_safely(installer):
    module, installed, calls = installer
    first = module.install()
    second = module.install()
    assert first == second
    assert calls[0] == ["codex", "plugin", "marketplace", "add", "wxofli/novel-weaver", "--ref", "v0.1.0", "--json"]
    assert calls[2] == ["uv", "sync", "--locked", "--project", str(installed)]
    assert calls[3] == ["uv", "run", "--locked", "--no-sync", "--project", str(installed), "novelctl", "--help"]
    assert len(calls) == 8
    assert not any("remove" in command for command in calls)


def test_installer_dry_run_does_not_execute(installer):
    module, _, calls = installer
    plan = module.install(local=ROOT, dry_run=True)
    assert plan["dryRun"]
    assert plan["commands"][0][4] == str(ROOT)
    assert calls == []


def test_installer_rejects_config_conflict_before_mutation(installer, monkeypatch, tmp_path):
    module, _, calls = installer
    home = tmp_path / "different-codex"
    home.mkdir()
    config = home / "config.toml"
    original = '[marketplaces.wxofli-novels]\nsource_type="local"\nsource="/someone/else"\n'
    config.write_text(original, encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    with pytest.raises(module.InstallError, match="different source/ref"):
        module.install()
    assert config.read_text(encoding="utf-8") == original
    assert calls == []


def test_installer_rejects_missing_path_before_sync(installer, monkeypatch):
    module, _, calls = installer
    def run(command, **kwargs):
        calls.append(command)
        return {"marketplaceName": module.MARKETPLACE} if "marketplace" in command else {}
    monkeypatch.setattr(module, "run", run)
    with pytest.raises(module.InstallError, match="lacks installedPath"):
        module.install()
    assert len(calls) == 2


def test_installer_stops_on_failed_sync(installer, monkeypatch):
    module, _, calls = installer
    original = module.run
    def run(command, **kwargs):
        if "sync" in command:
            calls.append(command)
            raise module.InstallError("offline dependency failure")
        return original(command, **kwargs)
    monkeypatch.setattr(module, "run", run)
    with pytest.raises(module.InstallError, match="offline dependency failure"):
        module.install()
    assert len(calls) == 3


@pytest.mark.parametrize("returncode,stdout,stderr,match", [(4, "", "registry unavailable", "registry unavailable"), (0, "not json", "", "valid JSON")])
def test_installer_subprocess_errors_are_explicit(monkeypatch, returncode, stdout, stderr, match):
    module = script("install")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], returncode, stdout, stderr))
    with pytest.raises(module.InstallError, match=match):
        module.run(["codex", "plugin", "list", "--json"], json_output=True)


def test_installer_missing_command_has_actionable_error(monkeypatch):
    module = script("install")
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    with pytest.raises(module.InstallError, match="not found on PATH"):
        module.find_command("codex")


def test_installer_windows_prefers_cmd(monkeypatch):
    module = script("install")
    monkeypatch.setattr(module.os, "name", "nt")
    looked_up = []
    def which(name):
        looked_up.append(name)
        return "C:/tools/codex.cmd" if name == "codex.cmd" else None
    monkeypatch.setattr(module.shutil, "which", which)
    assert module.find_command("codex").endswith(".cmd")
    assert looked_up == ["codex.cmd"]


def test_checksums_match_built_files(tmp_path):
    import hashlib
    module = script("checksums")
    for name in ("plugin.zip", "novel.whl", "novel.tar.gz"):
        (tmp_path / name).write_bytes(name.encode())
    output = module.checksums(tmp_path)
    for line in output.read_text(encoding="utf-8").splitlines():
        checksum, name = line.split("  ")
        assert checksum == hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()

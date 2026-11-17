"""Check delivery of editorial instructions, not the literary quality of prose."""
import importlib.util
import json
from pathlib import Path
import posixpath
import re
from urllib.parse import unquote, urlsplit
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def markdown_targets(source, content):
    """Resolve relative Markdown file links; anchors and external URLs are excluded."""
    for raw in re.findall(r"\]\(([^)]+)\)", content):
        link = urlsplit(raw.strip().strip("<>"))
        if link.scheme or link.netloc or not link.path.endswith(".md"):
            continue
        target = posixpath.normpath(posixpath.join(posixpath.dirname(source), unquote(link.path)))
        assert not target.startswith(("../", "/")), (source, raw)
        yield target


def test_editorial_local_references_exist():
    files = list((ROOT / "skills").rglob("*.md"))
    files += [ROOT / "AGENTS.md", ROOT / "README.md"]
    files += list((ROOT / "docs").glob("editorial-*.md"))
    for path in files:
        source = path.relative_to(ROOT).as_posix()
        for target in markdown_targets(source, path.read_text(encoding="utf-8")):
            assert (ROOT / target).is_file(), f"Broken reference from {source}: {target}"


def test_reading_entry_is_discoverable_from_manifest_and_router():
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    skill_root = manifest["skills"].removeprefix("./").rstrip("/")
    entry = f"{skill_root}/novel-read/SKILL.md"
    router = f"{skill_root}/novel/SKILL.md"
    targets = set(markdown_targets(router, (ROOT / router).read_text(encoding="utf-8")))
    assert entry in targets
    content = (ROOT / entry).read_text(encoding="utf-8")
    frontmatter = re.match(r"\A---\n(.*?)\n---\n", content, re.S)
    assert frontmatter, "Reading entry requires Skill metadata"
    assert re.search(r"^name: novel-read$", frontmatter[1], re.M)
    assert re.search(r"^description: \S.+$", frontmatter[1], re.M)


def test_packaged_editorial_dependency_graph_is_complete(tmp_path):
    spec = importlib.util.spec_from_file_location("editorial_package", ROOT / "scripts/package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive = module.package(tmp_path / "plugin.zip")
    with zipfile.ZipFile(archive) as payload:
        names = set(payload.namelist())
        manifest = json.loads(payload.read(".codex-plugin/plugin.json"))
        skill_root = manifest["skills"].removeprefix("./").rstrip("/")
        pending = [f"{skill_root}/novel/SKILL.md", "README.md"]
        visited = set()
        while pending:
            source = pending.pop()
            if source in visited:
                continue
            assert source in names, f"Unpackaged editorial dependency: {source}"
            visited.add(source)
            content = payload.read(source).decode("utf-8")
            pending.extend(markdown_targets(source, content))
        # These assets must remain reachable, not merely present in a source checkout.
        required = {
            f"{skill_root}/novel-read/SKILL.md",
            f"{skill_root}/novel/assets/book-agents.md",
            f"{skill_root}/novel/references/reading.md",
            f"{skill_root}/novel/references/review-modes.md",
            f"{skill_root}/novel/references/story-craft.md",
            f"{skill_root}/novel/references/craft-examples.md",
            "docs/editorial-verification.md",
            "docs/editorial-backend-roadmap.md",
            "docs/editorial-agents-init.md",
        }
        assert required <= visited
        assert "src/novel_weaver/store.py" in names
        # Developer instructions must not be installed as book-level instructions.
        assert "AGENTS.md" not in names

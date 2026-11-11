# Novel Weaver

[Chinese guide](README.md) · [Getting started (Chinese)](docs/getting-started.md) · [Technical reference (Chinese)](docs/advanced.md)

An evidence-backed fiction-writing plugin for Codex. Plan, draft, review and continue a novel with isolated memory for each book. Every fact points back to a source version and quotation; drafts become canon only when the author explicitly adopts that version.

Version 0.1.0 is a preview. It supports TXT/Markdown imports, local graph and keyword search, versioned drafts and recovery. Codex performs the writing and semantic extraction. Review its work; structural evidence checks do not guarantee correct story interpretation.

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/) and a Codex version supporting plugins and hooks. From this downloaded repository:

```sh
uv run --no-project python scripts/install.py
```

The installer registers `wxofli/novel-weaver` at `v0.1.0`, installs through Codex, then prepares the locked environment in Codex's returned `installedPath`. Before that tag is published, or for an extracted plugin ZIP, use `--local .`. Use `--dry-run` to inspect the plan.

Restart Codex, then review and trust the hooks in Settings > Hooks (CLI: `/hooks`). The installer never grants hook trust or deletes books. See [verification](docs/verification.md) for the actual host-validation boundary.

Open your book directory in Codex and ask it to create a book, draft a chapter, review it, then adopt that exact draft when you are satisfied. An original Chinese [sample manuscript](examples/雾港来信.txt) is included. Book data lives in `.novel/memory.sqlite`; back up the complete book directory using a consistent SQLite backup. Optional embedding/reranking services receive text only when you configure them.

[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md) · [MIT License](LICENSE)

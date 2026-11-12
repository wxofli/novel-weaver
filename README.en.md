# Novel Weaver

[Chinese guide](README.md) · [Getting started (Chinese)](docs/getting-started.md) · [Technical reference (Chinese)](docs/advanced.md)

An evidence-backed fiction-writing plugin for Codex. Plan, draft, review and continue a novel with isolated memory for each book. Every fact points back to a source version and quotation; drafts become canon only when the author explicitly adopts that version.

Version 0.1.4 is a preview with separate drafting and review context. Drafting with an explicit viewpoint uses what that viewpoint knows, believes or has heard. Review can retrieve author-level evidence. The plugin supports TXT/Markdown imports, local graph and keyword search, versioned drafts, recovery, and a cross-cultural adaptation workflow.

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/) and a Codex version supporting plugins and hooks. Extract the plugin ZIP from the [release page](https://github.com/wxofli/novel-weaver/releases/tag/v0.1.4) and run this in the extracted directory:

```sh
uv run --no-project python scripts/install.py
```

The installer registers `wxofli/novel-weaver` at `v0.1.4`, installs through Codex, then prepares the locked environment in the installed copy. Use `--local .` to install directly from the extracted files, or `--dry-run` to inspect the plan. For source checkouts, first run `python scripts/package.py` and extract its ZIP into a clean directory: Codex copies the entire local source. For an existing installation, see the [upgrade steps](docs/getting-started.md#更新与卸载).

The `novel-adapt` skill coordinates research, story analysis, cultural and character mapping, planning, drafting and review. It distinguishes authorized adaptation from independently created work and keeps source research separate from the new book's canon.

Restart Codex, then review and trust the hooks in Settings > Hooks (CLI: `/hooks`). The installer never grants hook trust or deletes books. See [verification](docs/verification.md) for the actual host-validation boundary.

Open your book directory in Codex and ask it to create a book, draft a chapter, review it, then adopt that exact draft when you are satisfied. An original Chinese [sample manuscript](examples/雾港来信.txt) is included. Book data lives in `.novel/memory.sqlite`; back up the complete book directory using a consistent SQLite backup. Optional embedding/reranking services receive text only when you configure them.

[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md) · [MIT License](LICENSE)

# Changelog

## Unreleased

Changes after the 0.1.1 preview will be recorded here.

## 0.1.1 — Codex desktop hooks

- Fixed an empty Hooks list in Codex desktop by packaging Novel Weaver with the Codex compatibility manifest. The installed plugin exposes all seven lifecycle hooks for review.
- Start MCP from the installed plugin directory using the environment prepared by the installer. Startup uses a cache inside that environment and skips dependency synchronization.
- Updated the installation and upgrade instructions. After upgrading, restart Codex and review the new installation in **Settings > Hooks**.

## 0.1.0 — Preview

First public preview: isolated book projects; immutable source versions; author adoption of reviewed drafts; quotation-backed graph memory; Chinese keyword search; optional vector search and reranking; TXT/Markdown import and sequential recovery; shared CLI/MCP core and lifecycle hooks.

Includes a portable Codex plugin, a pinned installer, original example manuscript, beginner guide and release checks. See [verification](docs/verification.md) for measured validation and host limitations.

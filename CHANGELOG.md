# Changelog

## Unreleased

Changes after the 0.1.4 preview will be recorded here.

## 0.1.4 — Cross-cultural adaptation workflow

- Add a cross-cultural adaptation workflow that coordinates research, story planning, drafting and review while preserving source, rights, project and author-adoption boundaries.
- Route adaptation requests through the main novel entry and document how to combine it with other available skills.
- Clarify that local development installations should use an extracted release package to avoid copying workspace caches, virtual environments or manuscripts into the plugin cache.

## 0.1.3 — Third-person narration

- Default to third-person narration in samples, new drafts and revisions. Use a first-person narrator only where the author explicitly requests it. Dialogue, clearly marked direct thoughts and letters can use first person in character.
- Carry narrative person in the scene brief, correct unapproved shifts before saving, and cite the draft in review when narrative person changes unexpectedly.
- Include the same rules in `AGENTS.md` when initializing a book project.

## 0.1.2 — Scene context and lean hooks

- Add a scene brief for goal, story time, constraints and reveal limits. Drafting with an explicit POV uses that viewpoint's knowledge. Review uses author-level evidence and references the exact draft version.
- Keep the scene brief within the context budget and add optional evidence and style excerpts as space allows. Review, planning and query no longer write draft tickets.
- Ship three default hooks for session start, prompt submission and stop. Stop can only resume fresh candidate memory or review work from the current turn. Author adoption remains explicit.

## 0.1.1 — Codex desktop hooks

- Fixed an empty Hooks list in Codex desktop by packaging Novel Weaver with the Codex compatibility manifest. The installed plugin exposes all seven lifecycle hooks for review.
- Start MCP from the installed plugin directory using the environment prepared by the installer. Startup uses a cache inside that environment and skips dependency synchronization.
- Updated the installation and upgrade instructions. After upgrading, restart Codex and review the new installation in **Settings > Hooks**.

## 0.1.0 — Preview

First public preview: isolated book projects; immutable source versions; author adoption of reviewed drafts; quotation-backed graph memory; Chinese keyword search; optional vector search and reranking; TXT/Markdown import and sequential recovery; shared CLI/MCP core and lifecycle hooks.

Includes a portable Codex plugin, a pinned installer, original example manuscript, beginner guide and release checks. See [verification](docs/verification.md) for measured validation and host limitations.

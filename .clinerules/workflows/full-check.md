# RDE Full Release Check

Run from the repository root with Python 3.11+ / uv and Node 22+. Stop on failures;
do not weaken case accounting, PII checks or provenance to pass a gate.

## Python and live MCP contracts

```sh
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m "not vendor_integration"
uv run python scripts/audit_mcp_surface.py
```

The live audit enumerates all 50 tools. The parameterized boundary suite checks
every tool; numerical clinical/paired and autoresearch tests cover their own
success/failure contracts. This is not exhaustive validation of every study design.

## Extension and canonical assets

```sh
npm --prefix vscode-extension ci
npm --prefix vscode-extension run sync-assets
npm --prefix vscode-extension run sync-assets:check
npm --prefix vscode-extension run lint
npm --prefix vscode-extension test
npm --prefix vscode-extension run test:install-smoke
npm --prefix vscode-extension run package -- --no-yarn
npm --prefix vscode-extension run validate -- --skip-tests
```

`asset-manifest.mjs` declares the host-neutral canonical copies; the remaining
host-specific skills/prompts are checked for presence, not silently overwritten.
CI repeats install/package checks on Windows, Linux and Intel/ARM macOS.

## Package integrity and pre-commit

```sh
uv build
uv run python scripts/audit_release_artifacts.py
uv run --with pre-commit pre-commit run --all-files
git diff --check
```

Direct main commits are allowed only when explicitly requested by the user; in
that case skip only `no-commit-to-branch`. Keep all other hooks. Never commit
raw data, generated reports, `.venv`, `dist`, extension `out` or VSIX binaries.

## Website and publishing

- Test desktop/mobile navigation, language switching, method filters, copy action,
  legacy guide routes, image accessibility and browser errors.
- Compare native SVG/HTML against the approved concepts; retain QA evidence outside
  the source tree.
- Synchronize Python/package/lock versions, changelog and Memory Bank.
- Push reviewed segments to main, then a matching version tag. Verify remote CI,
  GitHub release assets, and each configured marketplace publishing outcome.
- Marketplace jobs without credentials must be reported as skipped, not published.

The optional vendor integration suite requires its separately configured Docker
services. Record it as skipped when unavailable; Docker is not a core RDE gate.

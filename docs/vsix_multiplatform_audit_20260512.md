# VSIX Multi-Platform Audit - 2026-05-12

## Scope

This audit checks whether the Research Data Explorer VSIX is merely packaged on one platform or is guarded as a practical multi-platform install path for Windows, macOS, and Linux.

Reference comparison: `u9401066/med-paper-assistant`, especially its VSIX release workflow and `uvManager` runtime handling.

## Finding Summary

| Area | Before | Fix Applied |
| --- | --- | --- |
| Platform claim | README listed Windows/macOS/Linux support. | Documentation now ties support to a CI smoke matrix. |
| CI evidence | Extension tests and VSIX packaging ran on Ubuntu only. | CI and publish workflows now run VSIX smoke on `ubuntu-latest`, `windows-latest`, `macos-13`, and `macos-14`. |
| VSIX package shape | Bundled Python project smoke existed, but only local/Ubuntu-gated. | Bundled install-shape smoke is now part of each platform matrix job. |
| MCP subprocess env | `buildMcpEnv()` only set RDE/Python UTF-8 variables. | MCP env now preserves PATH/HOME/TEMP and Windows/macOS/Linux runtime variables. |
| uv/tool lookup | Tool lookup checked known uv tool paths but did not search all enriched PATH directories. | Installed-tool discovery now searches enriched PATH first, then platform-specific uv/Homebrew/snap locations. |
| Regression coverage | No direct `uvManager` test file. | Added `test/uvManager.test.ts` for uvx path, PATH enrichment, MCP env, and tool discovery. |

## Practical Multi-Platform Assessment

The extension is now designed to be platform-neutral in three layers:

1. VS Code layer: `package.json` does not restrict `os` or `platform`, and the extension uses VS Code MCP server definition APIs rather than platform-specific shell launchers.
2. Node layer: path assembly uses Node `path` and avoids hard-coded separators in the extension runtime.
3. Python/MCP layer: packaged VSIX runs the bundled Python project via `uv run --project ... python -m rde`, with UTF-8 env plus inherited runtime variables needed by uv and Python subprocesses.

The repo still cannot claim that Linux/macOS were locally exercised from this Windows workstation. The intended evidence source is now GitHub Actions: each push/PR and each extension publish run executes the VSIX smoke matrix across Ubuntu, Windows, macOS Intel, and macOS Apple Silicon runners.

## Why The Env Fix Matters

VS Code launched from a GUI can have a reduced environment, especially on macOS. If the MCP subprocess does not receive enriched PATH/HOME/TEMP-style variables, the server can fail even when the VSIX installs correctly:

- `uv` or `uvx` may not be discoverable.
- uv cache/temp resolution can fail on Windows.
- Homebrew paths such as `/opt/homebrew/bin` may be missing on macOS.
- subprocess tools may behave differently than in an interactive terminal.

RDE now follows the same design lesson as MedPaper Assistant: the VSIX should preserve the runtime environment it needs instead of assuming an interactive shell.

## Verification Commands

Local Windows verification:

```powershell
cd vscode-extension
npm run sync-assets:check
npm run compile
npm run test:install-smoke
npm run package -- --no-yarn
npm run validate -- --skip-tests
```

Node 20 test verification on machines whose default `node` is too old:

```powershell
npx -p node@20 node ./scripts/run-with-npm-node.cjs ./node_modules/vitest/vitest.mjs run test/utils.test.ts test/extensionHelpers.test.ts test/uvManager.test.ts
```

CI verification:

```text
.github/workflows/ci.yml
  extension-cross-platform-smoke:
    ubuntu-latest
    windows-latest
    macos-13
    macos-14

.github/workflows/publish-extension.yml
  cross-platform-smoke:
    ubuntu-latest
    windows-latest
    macos-13
    macos-14
```

## Remaining Risk

- The matrix validates install shape, helper logic, package creation, and package validation. It does not yet open a real VS Code UI on all three platforms.
- A future stronger smoke could launch `code --install-extension <vsix>` or use `@vscode/test-electron` on each runner to verify activation and MCP server definition registration in an extension host.
- Full governed real-dataset RDE execution should remain a separate, slower smoke because it creates large artifacts and may depend on test data availability.

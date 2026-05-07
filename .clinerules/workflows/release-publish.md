# Release Publish (asset-aware-mcp)

Prepare and publish a new tagged release for this repository.

## Step 1: Ensure a clean working directory
<execute_command>
<command>git status --porcelain</command>
</execute_command>

If there are uncommitted changes, ask whether to continue or stop.

## Step 2: Choose how to bump the version
<ask_followup_question>
<question>How should I determine the next version?</question>
<options>["Patch (x.y.Z)", "Minor (x.Y.0)", "Major (X.0.0)", "Custom (enter exact X.Y.Z)"]</options>
</ask_followup_question>

Read the current version from `pyproject.toml`, compute the next semantic version if Patch/Minor/Major was chosen, and ask the user to confirm the exact `X.Y.Z`.

If Custom was chosen, ask the user for the exact version string (must match `^\\d+\\.\\d+\\.\\d+$` and have no leading `v`).

## Step 3: Update versions everywhere (keep in sync)
Update these files to the chosen version:
- `pyproject.toml`
- `src/__init__.py`
- `Dockerfile` image version label
- `vscode-extension/package.json`
- `vscode-extension/package-lock.json`
- `uv.lock` (run `uv lock` if needed)
- `CHANGELOG.md` (add a new dated section)

If any tests have version pins/expectations, update them too.

## Step 4: Run full verification
Execute the steps in `.clinerules/workflows/full-check.md` in this task.
If anything fails, stop and report the failures.

VSIX install/activation smoke is required for release. On Linux, prefer:
<execute_command>
<command>(cd vscode-extension && xvfb-run -a npm run test:install-smoke -- --require-activation)</command>
</execute_command>

Validate release harness parity and built artifacts:
<execute_command>
<command>python3 scripts/audit_release_harness.py</command>
</execute_command>

<execute_command>
<command>python3 scripts/audit_release_artifacts.py</command>
</execute_command>

## Step 5: Commit
Stage changes, then create a release commit.

<execute_command>
<command>git add -A</command>
</execute_command>

Validate the version in `pyproject.toml` is a strict `X.Y.Z`:
<execute_command>
<command>python3 scripts/get_version.py --strict-semver</command>
</execute_command>

Create a release commit:
<execute_command>
<command>VERSION="$(python3 scripts/get_version.py --strict-semver)"; git commit -m "Release $VERSION"</command>
</execute_command>

## Step 6: Push commit to origin
Push the default branch (`master`) to `origin`. If git credentials are missing, stop and ask the user to configure authentication.

<execute_command>
<command>git push origin master</command>
</execute_command>

## Step 7: Tag + push tag
Create an **annotated** tag named `vX.Y.Z` and push it to origin.

<execute_command>
<command>VERSION="$(python3 scripts/get_version.py --strict-semver)"; git tag -a "v$VERSION" -m "Release v$VERSION"</command>
</execute_command>

<execute_command>
<command>VERSION="$(python3 scripts/get_version.py --strict-semver)"; git push origin "v$VERSION"</command>
</execute_command>

Verify the tag exists on the remote (should include `refs/tags/vX.Y.Z`):
<execute_command>
<command>git ls-remote --tags origin</command>
</execute_command>

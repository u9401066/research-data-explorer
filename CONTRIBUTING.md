# Contributing

## Development setup

```bash
python3 -m pip install -e ".[dev]"
pre-commit install
```

## Baseline checks

Before opening a pull request, run:

```bash
python3 -m pytest -q
pre-commit run --all-files
```

## Change rules for this repo

1. If you change workflow behavior, update tests in `tests/`.
2. If you change governance semantics, update these together:
   - `README.md`
   - `AGENTS.md`
   - `.github/copilot-instructions.md`
   - `.github/agent-control.yaml`
3. Do not weaken phase gates or audit logging just to make a flow easier.
4. When touching vendor delegation, document local fallback behavior.
5. Keep new files and docs aligned with the repository's DDD vocabulary.

## Pull request checklist

- explain the user-visible behavior change
- list impacted phases or artifacts
- mention added or updated tests
- call out vendor/environment prerequisites if applicable

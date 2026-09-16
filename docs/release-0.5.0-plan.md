# RDE 0.5.0 release workboard

Baseline: `main` = `origin/main` = `2b20221` after fetch + fast-forward check
on 2026-09-16. User explicitly requested all improvements on main.

RDE remains a local-first MCP + agent-harness plugin. It does not become an
independent LLM service, automatically approve plans, or promote exploratory
p-values to confirmatory findings.

Primary acceptance criterion: help agents collaborate on clinically meaningful,
publication-level reproducible reports without writing extensive ad hoc code.
Hypothesis generation and methodological discussion stay open-ended. Guardrails
protect data, execution provenance and claim promotion, not agent thinking.

## Segmented delivery and evidence

- [x] Official MCP SDK 2.2 migration; era-neutral Client tests, protocol errors,
  structured responses, tool annotations, resources/prompts and resolver use.
- [x] Review every registered tool: schema, effects, gates, errors, artifacts,
  documentation and VSIX inventory; keep an executable audit manifest.
- [x] Clinical methods: explicit denominators, estimates/CIs, paired binary
  outcomes, diagnostic accuracy, agreement and longitudinal models; regression
  tests, assumptions and method-specific caveats.
- [x] Autoresearch: compare multiple primary repos, carry provenance and frozen
  budgets, deterministic deduplication, failed/null results, stop/resume safety.
- [x] Website: complete information architecture, responsive accessible design,
  real installation paths, method catalog, Mermaid/SVG workflows, browser QA.
- [ ] README, agent harness, MEM+, extension SVGs/version, release tests, package,
  segmented commits/pushes, CI/Pages/release verification.

## SDK references checked 2026-09-16

- [Official SDK releases](https://github.com/modelcontextprotocol/python-sdk/releases)
- [Migration guide](https://py.sdk.modelcontextprotocol.io/migration/)
- [Resolver dependencies](https://py.sdk.modelcontextprotocol.io/handlers/dependencies/)
- [In-memory client testing](https://py.sdk.modelcontextprotocol.io/getting-started/testing/)

The official SDK stable release line is v2 (2.2.0 at review). Experimental Tasks
is not implemented in this release: RDE's durable work queue remains an
application-level artifact contract, not an advertised MCP Tasks extension.

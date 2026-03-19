# Security Policy

## Scope

This repository handles analysis workflow governance, report generation, and delegated statistical execution. Security issues are especially relevant when they affect:

- PII detection and output sanitization
- unsafe report exports or leaked local paths
- unintended bypass of phase or artifact gates
- insecure vendor delegation to `automl-stat-mcp`

## Reporting

Please report security issues privately to the repository maintainers instead of opening a public issue.

Include:

- affected file or component
- reproduction steps
- expected versus actual behavior
- whether PII, credential leakage, or audit bypass is involved

## High-priority classes in this repo

1. PII false negatives in intake or report outputs
2. audit log tampering or append-only bypass
3. phase-gate bypass that allows unauthorized analysis paths
4. vendor request handling that exposes secrets or unsafe paths

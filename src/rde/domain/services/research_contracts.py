"""Open-ended agent proposals with deterministic execution provenance."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def contract_fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str, allow_nan=False).encode(
            "utf-8"
        )
    ).hexdigest()


def research_baseline(schema: dict, plan: dict, roles: dict) -> dict[str, str]:
    """Hash design inputs, not raw observations; data lineage remains separate."""
    return {
        key: contract_fingerprint(value)
        for key, value in {"schema": schema, "plan": plan, "roles": roles}.items()
    }


def combine_research_proposals(
    agent_proposals: list[dict] | None, builtins: list[dict]
) -> list[dict]:
    """User/agent ideas have first access to the budget, without a hypothesis menu."""
    proposals = []
    for index, proposal in enumerate(agent_proposals or []):
        if not isinstance(proposal, dict) or not str(proposal.get("hypothesis") or "").strip():
            raise ValueError(f"agent_proposals[{index}] requires a nonempty hypothesis.")
        if not str(proposal.get("reason") or "").strip():
            raise ValueError(f"agent_proposals[{index}] requires a clinical/methodological reason.")
        contract = proposal.get("analysis_contract") or {}
        if not isinstance(contract, dict):
            raise ValueError("analysis_contract must be an object; omit it for an idea-only task.")
        variables = proposal.get("variables") or []
        if not isinstance(variables, list) or not all(
            isinstance(value, str) for value in variables
        ):
            raise ValueError("Proposal variables must be a list of column names.")
        if contract and (not contract.get("tool") or not contract.get("analysis_type")):
            raise ValueError("Executable analysis_contract requires tool and analysis_type.")
        proposals.append(
            {
                **proposal,
                "proposal_source": "agent",
                "analysis_contract": dict(contract),
                "variables": list(variables),
            }
        )
    proposals.extend({**proposal, "proposal_source": "builtin"} for proposal in builtins)
    output, seen = [], set()
    for proposal in proposals:
        fingerprint = contract_fingerprint(
            proposal.get("analysis_contract")
            or {"hypothesis": proposal.get("hypothesis"), "variables": proposal.get("variables")}
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        output.append({**proposal, "contract_fingerprint": fingerprint})
    return output

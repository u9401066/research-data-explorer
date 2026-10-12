"""Published research port rules. Hosts resolve persisted identity and facts.

Topology compatibility is never approval; native phase/source gates still run.
"""

import hashlib
import json
from pathlib import Path


def canvas_contract() -> dict:
    return json.loads(Path(__file__).with_name("canvas_contract.json").read_text("utf-8"))


def validate_connection(source_type: str, transition: str, facts: dict) -> dict:
    contract = canvas_contract()
    if source_type not in contract["nodes"] or transition not in contract["transitions"]:
        raise ValueError("Unknown research node or transition.")
    if set(facts) != set(contract["facts"]) or any(type(v) is not bool for v in facts.values()):
        raise ValueError("All research facts must be explicit booleans derived by the host.")
    rule = contract["transitions"][transition]
    output = contract["nodes"][source_type]["output"]
    code = (
        "INCOMPATIBLE_PORT"
        if output not in rule["accepts"]
        else "RESEARCH_STAGE_CONFLICT"
        if any(facts[k] for k in rule["forbids"])
        else "MISSING_RESEARCH_PREREQUISITE"
        if any(not facts[k] for k in rule["requires"])
        else None
    )
    return {
        "contract": contract["contract"],
        "source_type": source_type,
        "transition": transition,
        "output": output,
        "target": rule["sampleTarget"] if facts["samplePlan"] else rule["target"],
        "relation": rule["relation"],
        "allowed": code is None,
        "code": code,
        "facts_sha256": hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest(),
        "authorization": "topology_only_not_execution_permission",
    }

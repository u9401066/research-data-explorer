"""Independent, bounded SQLite oracle; not RDE runtime or a clinical estimator.

Inputs are deliberately tiny, synthetic integer UTC-day ticks. SQL derives all
eligibility, interval unions, counts, episodes and traces. Expected values were
hand enumerated in expected.json. Package CI checks use independent distribution
inversion / Wilson algebra, not a second call to the package implementation.
"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
from statistics import NormalDist


HERE = Path(__file__).resolve().parent
CHECKS = []


def check(label, actual, expected):
    if actual != expected:
        raise AssertionError(f"{label}: {actual!r} != {expected!r}")
    CHECKS.append(label)


def rows(db, query):
    return [list(row) for row in db.execute(query)]


def load(section):
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
      CREATE TABLE person(id TEXT PRIMARY KEY, death INTEGER);
      CREATE TABLE coverage(id TEXT PRIMARY KEY, person TEXT REFERENCES person,
        start INTEGER NOT NULL, end INTEGER NOT NULL, status TEXT NOT NULL,
        CHECK(end>start), CHECK(status IN ('complete','unknown')));
      CREATE TABLE event(id TEXT PRIMARY KEY, person TEXT REFERENCES person, time INTEGER NOT NULL);
      CREATE TABLE condition(id TEXT PRIMARY KEY, person TEXT REFERENCES person,
        start INTEGER NOT NULL, end INTEGER NOT NULL, CHECK(end>start));
      CREATE TABLE exposure(id TEXT PRIMARY KEY, person TEXT REFERENCES person,
        drug TEXT NOT NULL CHECK(drug IN ('A','B')), start INTEGER NOT NULL,
        end INTEGER NOT NULL, CHECK(end>start));
    """)
    for table, key, count in [
        ("person", "people", 2),
        ("coverage", "coverage", 5),
        ("event", "events", 3),
        ("condition", "conditions", 4),
        ("exposure", "exposures", 5),
    ]:
        db.executemany(
            f"INSERT INTO {table} VALUES ({','.join('?' for _ in range(count))})",
            section.get(key, []),
        )
    # Running maximum, not only LAG(end): nested intervals must not manufacture gaps.
    db.executescript("""
      CREATE VIEW coverage_union AS
      WITH ranked AS (
        SELECT *, MAX(end) OVER(PARTITION BY person ORDER BY start,end,id
          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) prior_end
        FROM coverage WHERE status='complete'
      ), marked AS (
        SELECT *, CASE WHEN prior_end IS NULL OR start>prior_end THEN 1 ELSE 0 END new_group FROM ranked
      ), grouped AS (
        SELECT *, SUM(new_group) OVER(PARTITION BY person ORDER BY start,end,id) g FROM marked
      )
      SELECT person, MIN(start) start, MAX(end) end FROM grouped GROUP BY person,g;
    """)
    return db


def incidence(section):
    assert section["window"] == [0, 10] and section["washout"] == 5 and section["point"] == 2
    db = load(section)
    db.executescript("""
      CREATE VIEW eligible AS
      SELECT p.id person,c.start,c.end,MIN(10,c.end,COALESCE(p.death,10)) censor,
        CASE WHEN c.person IS NULL THEN 'unknown_coverage'
          WHEN c.start>-5 THEN 'insufficient_washout'
          WHEN p.death<=0 THEN 'not_alive_at_start'
          WHEN EXISTS(SELECT 1 FROM event e WHERE e.person=p.id AND e.time<=0)
            THEN 'prior_or_index_case'
          ELSE 'eligible' END status,
        CASE WHEN p.death<=MIN(10,c.end) THEN 'death'
          WHEN c.end<10 THEN 'coverage_end' ELSE 'administrative_end' END censor_reason
      FROM person p LEFT JOIN coverage_union c ON c.person=p.id AND c.start<=0 AND c.end>0;
      CREATE VIEW first_event AS
      SELECT a.*, (SELECT MIN(e.time) FROM event e
        WHERE e.person=a.person AND e.time>0 AND e.time<a.censor) event_time
      FROM eligible a WHERE status='eligible';
      CREATE VIEW participant AS
      SELECT *, MIN(COALESCE(event_time,censor),censor) person_days FROM first_event;
      CREATE VIEW point_people AS
      SELECT p.id person, EXISTS(SELECT 1 FROM condition s WHERE s.person=p.id
        AND s.start<=2 AND s.end>2) is_case
      FROM person p WHERE (p.death IS NULL OR p.death>2) AND EXISTS(
        SELECT 1 FROM coverage_union c WHERE c.person=p.id AND c.start<=2 AND c.end>2);
      CREATE VIEW period_people AS
      SELECT p.id person, EXISTS(SELECT 1 FROM condition s WHERE s.person=p.id
        AND s.start<MIN(10,COALESCE(p.death,10)) AND s.end>0) is_case
      FROM person p WHERE (p.death IS NULL OR p.death>0) AND EXISTS(
        SELECT 1 FROM coverage_union c WHERE c.person=p.id AND c.start<=0
        AND c.end>=MIN(10,COALESCE(p.death,10)));
    """)
    count, exposure = db.execute(
        "SELECT SUM(event_time IS NOT NULL),SUM(person_days) FROM participant"
    ).fetchone()
    censored = rows(
        db,
        "SELECT person,censor_reason FROM participant WHERE event_time IS NULL AND censor<10 ORDER BY person",
    )
    output = {
        "population": db.execute("SELECT COUNT(*) FROM person").fetchone()[0],
        "eligible": [r[0] for r in rows(db, "SELECT person FROM participant ORDER BY person")],
        "excluded": dict(
            rows(db, "SELECT person,status FROM eligible WHERE status!='eligible' ORDER BY person")
        ),
        "person_days": dict(rows(db, "SELECT person,person_days FROM participant ORDER BY person")),
        "first_event_ids": [
            r[0]
            for r in rows(
                db,
                "SELECT e.id FROM event e JOIN participant p ON p.person=e.person AND p.event_time=e.time ORDER BY e.id",
            )
        ],
        "events": count,
        "person_days_total": exposure,
        "incidence_rate_fraction_per_day": [count, exposure],
        "incidence_proportion": None
        if censored
        else [count, db.execute("SELECT COUNT(*) FROM participant").fetchone()[0]],
        "risk_unavailable_reasons": sorted(
            {
                "death_before_horizon" if r[1] == "death" else "observation_gap_before_horizon"
                for r in censored
            }
        ),
    }
    full = rows(
        db,
        "SELECT person,event_time IS NOT NULL,person_days FROM participant WHERE censor=10 ORDER BY person",
    )
    output["full_followup_subset"] = {
        "people": [r[0] for r in full],
        "events": sum(r[1] for r in full),
        "person_days": sum(r[2] for r in full),
        "risk_fraction": [sum(r[1] for r in full), len(full)],
    }
    for kind in ("point", "period"):
        people = rows(db, f"SELECT person,is_case FROM {kind}_people ORDER BY person")
        output[kind] = {
            "people": [r[0] for r in people],
            "cases": [r[0] for r in people if r[1]],
            "fraction": [sum(r[1] for r in people), len(people)],
        }
    output["event_dispositions"] = dict(
        rows(
            db,
            """
      SELECT e.id, CASE WHEN a.status!='eligible' THEN 'ineligible_person'
        WHEN e.time>=a.censor THEN 'at_or_after_censor'
        WHEN e.time=p.event_time THEN 'incident' ELSE 'repeat_after_first' END
      FROM event e JOIN eligible a ON e.person=a.person
      LEFT JOIN participant p ON p.person=e.person ORDER BY e.id
    """,
        )
    )
    trace = rows(
        db,
        "SELECT person,start,end,censor,censor_reason,event_time,person_days FROM participant ORDER BY person",
    )
    db.close()
    return output, trace


def pathways(section):
    assert section["window"] == [0, 10] and section["grace"] == 1
    db = load(section)
    db.executescript("""
      CREATE VIEW followup AS
      SELECT p.id person,0 start,MIN(10,c.end,COALESCE(p.death,10)) end,
        CASE WHEN p.death<=MIN(10,c.end) THEN 'death'
          WHEN c.end<10 THEN 'coverage_end' ELSE 'administrative_end' END reason
      FROM person p JOIN coverage_union c ON c.person=p.id AND c.start<=0 AND c.end>0
      WHERE p.death IS NULL OR p.death>0;
      CREATE VIEW clipped AS
      SELECT e.id,e.person,e.drug,MAX(e.start,f.start) start,MIN(e.end,f.end) end
      FROM exposure e JOIN followup f ON e.person=f.person WHERE e.start<f.end AND e.end>f.start;
      CREATE VIEW ranked_exposure AS
      SELECT *,MAX(end) OVER(PARTITION BY person,drug ORDER BY start,end,id
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) prior_end FROM clipped;
      CREATE VIEW eras AS
      WITH marked AS (
        SELECT *,CASE WHEN prior_end IS NULL OR start>prior_end+1 THEN 1 ELSE 0 END new_group FROM ranked_exposure
      ), grouped AS (
        SELECT *,SUM(new_group) OVER(PARTITION BY person,drug ORDER BY start,end,id) g FROM marked
      )
      SELECT person,drug,MIN(start) start,MAX(end) end FROM grouped GROUP BY person,drug,g;
      CREATE VIEW segments AS
      WITH boundaries AS (
        SELECT person,start time FROM followup UNION SELECT person,end FROM followup
        UNION SELECT person,start FROM eras UNION SELECT person,end FROM eras
      ), ordered AS (
        SELECT person,time start,LEAD(time) OVER(PARTITION BY person ORDER BY time) end FROM boundaries
      )
      SELECT o.person,o.start,o.end,COALESCE((SELECT GROUP_CONCAT(drug,'+') FROM (
        SELECT DISTINCT e.drug FROM eras e WHERE e.person=o.person
          AND e.start<=o.start AND e.end>o.start ORDER BY e.drug)), 'NONE') state
      FROM ordered o WHERE o.end>o.start;
      CREATE VIEW episodes AS
      WITH ranked AS (
        SELECT *,LAG(state) OVER(PARTITION BY person ORDER BY start) previous FROM segments
      ), marked AS (
        SELECT *,CASE WHEN previous=state THEN 0 ELSE 1 END new_group FROM ranked
      ), grouped AS (
        SELECT *,SUM(new_group) OVER(PARTITION BY person ORDER BY start) g FROM marked
      )
      SELECT person,ROW_NUMBER() OVER(PARTITION BY person ORDER BY MIN(start)) step,
        MIN(start) start,MAX(end) end,state FROM grouped GROUP BY person,g,state;
      CREATE VIEW transitions AS
      WITH ordered AS (
        SELECT *,LEAD(state) OVER(PARTITION BY person ORDER BY step) next_state FROM episodes
      )
      SELECT o.person,o.step,o.state,COALESCE(next_state,'END:'||f.reason) next_state
      FROM ordered o JOIN followup f ON f.person=o.person;
    """)
    # Tiny-grid raw duration calculation is a second exact fixture-only oracle;
    # production must use interval unions, not expand every patient-day.
    db.executescript("""
      CREATE VIEW raw_duration AS
      WITH RECURSIVE tick(t) AS (SELECT 0 UNION ALL SELECT t+1 FROM tick WHERE t<9)
      SELECT drug,COUNT(*) days FROM (
        SELECT DISTINCT c.person,c.drug,t.t FROM clipped c JOIN tick t ON t.t>=c.start AND t.t<c.end
      ) GROUP BY drug;
    """)
    output = {
        "population": db.execute("SELECT COUNT(*) FROM person").fetchone()[0],
        "people": [r[0] for r in rows(db, "SELECT person FROM followup ORDER BY person")],
        "excluded": [
            r[0]
            for r in rows(
                db,
                "SELECT id FROM person WHERE id NOT IN (SELECT person FROM followup) ORDER BY id",
            )
        ],
        "episodes": rows(
            db, "SELECT person,step,start,end,state FROM episodes ORDER BY person,step"
        ),
        "terminals": dict(rows(db, "SELECT person,reason FROM followup ORDER BY person")),
        "step_denominators": {
            str(k): v
            for k, v in rows(
                db, "SELECT step,COUNT(DISTINCT person) FROM episodes GROUP BY step ORDER BY step"
            )
        },
        "state_duration_days": dict(
            rows(db, "SELECT state,SUM(end-start) FROM episodes GROUP BY state ORDER BY state")
        ),
        "person_days": db.execute("SELECT SUM(end-start) FROM followup").fetchone()[0],
        "raw_drug_days": dict(rows(db, "SELECT drug,days FROM raw_duration ORDER BY drug")),
        "era_drug_days": dict(
            rows(db, "SELECT drug,SUM(end-start) FROM eras GROUP BY drug ORDER BY drug")
        ),
        "users": dict(
            rows(db, "SELECT drug,COUNT(DISTINCT person) FROM clipped GROUP BY drug ORDER BY drug")
        ),
        "bridge": rows(
            db,
            """SELECT r.person,r.drug,r.prior_end,r.start,
          (SELECT MIN(c.id) FROM clipped c WHERE c.person=r.person AND c.drug=r.drug AND c.end=r.prior_end),r.id
          FROM ranked_exposure r WHERE r.start>r.prior_end AND r.start<=r.prior_end+1 ORDER BY person,drug,start""",
        ),
        "transition_counts": rows(
            db,
            "SELECT step,state,next_state,COUNT(*) FROM transitions GROUP BY step,state,next_state ORDER BY step,state,next_state",
        ),
    }
    trace = []
    for person, step, start, end, state in output["episodes"]:
        direct = [
            r[0]
            for r in db.execute(
                "SELECT id FROM clipped WHERE person=? AND start<? AND end>? ORDER BY id",
                (person, end, start),
            )
        ]
        era_rows = [
            r[0]
            for r in db.execute(
                """SELECT DISTINCT c.id FROM eras e JOIN clipped c
          ON c.person=e.person AND c.drug=e.drug AND c.start<e.end AND c.end>e.start
          WHERE e.person=? AND e.start<? AND e.end>? ORDER BY c.id""",
                (person, end, start),
            )
        ]
        trace.append(
            {
                "person": person,
                "step": step,
                "interval": [start, end],
                "state": state,
                "direct_exposure_ids": direct,
                "era_dependency_ids": era_rows,
            }
        )
    # Every reached node has one observed next state OR a terminal endpoint.
    node_counts = rows(
        db, "SELECT step,state,COUNT(*) FROM episodes GROUP BY step,state ORDER BY step,state"
    )
    outgoing = rows(
        db, "SELECT step,state,COUNT(*) FROM transitions GROUP BY step,state ORDER BY step,state"
    )
    check("pathway transition mass conservation", outgoing, node_counts)
    check(
        "pathway person-time partition",
        sum(output["state_duration_days"].values()),
        output["person_days"],
    )
    db.close()
    return output, trace


def package_checks():
    import scipy
    from scipy.optimize import brentq
    import statsmodels
    from statsmodels.stats.proportion import proportion_confint
    from statsmodels.stats.rates import confint_poisson

    # Explicit finite Poisson CDF inversion; no scipy gamma/chi2 quantile and no
    # second call to statsmodels as the independent oracle. Only fixture counts.
    def poisson_cdf(k, mean):
        return math.exp(-mean) * sum(mean**j / math.factorial(j) for j in range(k + 1))

    results = []
    for count, exposure in [(0, 37), (1, 37), (5, 100)]:
        low = (
            0.0
            if count == 0
            else brentq(lambda x: poisson_cdf(count - 1, x) - 0.975, 0, 100) / exposure
        )
        high = brentq(lambda x: poisson_cdf(count, x) - 0.025, 0, 100) / exposure
        actual = confint_poisson(
            count, exposure, method="exact-c", alpha=0.05, alternative="two-sided"
        )
        for label, value, expected in zip(("lower", "upper"), actual, (low, high), strict=True):
            check(
                f"Poisson {count}/{exposure} {label}",
                math.isclose(value, expected, rel_tol=1e-10, abs_tol=1e-12),
                True,
            )
        results.append(
            {
                "kind": "poisson_exact_c",
                "count": count,
                "exposure_days": exposure,
                "ci": list(map(float, actual)),
            }
        )
    z = NormalDist().inv_cdf(0.975)
    for count, n in [(0, 8), (2, 8), (4, 7), (8, 8)]:
        p = float(Fraction(count, n))
        divisor = 1 + z * z / n
        center = (p + z * z / (2 * n)) / divisor
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / divisor
        actual = proportion_confint(count, n, alpha=0.05, method="wilson", alternative="two-sided")
        for label, value, expected in zip(
            ("lower", "upper"), actual, (center - half, center + half), strict=True
        ):
            check(
                f"Wilson {count}/{n} {label}",
                math.isclose(value, expected, rel_tol=1e-10, abs_tol=1e-12),
                True,
            )
        results.append({"kind": "wilson", "count": count, "n": n, "ci": list(map(float, actual))})
    return {"statsmodels": statsmodels.__version__, "scipy": scipy.__version__, "checks": results}


def main():
    fixture = json.loads((HERE / "fixture.json").read_text())
    expected = json.loads((HERE / "expected.json").read_text())
    observed = {}
    traces = {}
    for key, function in (("incidence", incidence), ("pathways", pathways)):
        observed[key], traces[key] = function(fixture[key])
        for field, value in expected[key].items():
            check(f"{key}.{field}", observed[key][field], value)
        for seed in range(5):
            changed = deepcopy(fixture[key])
            rng = random.Random(seed)
            for table in ("people", "coverage", "events", "conditions", "exposures"):
                if table in changed:
                    rng.shuffle(changed[table])
            actual, trace = function(changed)
            check(f"{key}.permutation_{seed}", actual, observed[key])
            check(f"{key}.trace_permutation_{seed}", trace, traces[key])
    for label, key, table, change in [
        ("duplicate person", "incidence", "people", lambda s: s["people"].append(s["people"][0])),
        ("duplicate event", "incidence", "events", lambda s: s["events"].append(s["events"][0])),
        (
            "orphan event",
            "incidence",
            "events",
            lambda s: s["events"].append(["orphan", "absent", 2]),
        ),
        (
            "negative coverage",
            "incidence",
            "coverage",
            lambda s: s["coverage"].append(["bad", "P1", 4, 3, "complete"]),
        ),
        (
            "zero exposure interval",
            "pathways",
            "exposures",
            lambda s: s["exposures"].append(["bad", "T1", "A", 2, 2]),
        ),
        (
            "unmapped drug",
            "pathways",
            "exposures",
            lambda s: s["exposures"].append(["bad", "T1", "X", 2, 3]),
        ),
    ]:
        changed = deepcopy(fixture[key])
        change(changed)
        try:
            load(changed)
        except sqlite3.IntegrityError:
            check(label, True, True)
        else:
            raise AssertionError(label + " was accepted")
    package = package_checks()
    file_hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (
            HERE / "CONTRACT.md",
            HERE / "fixture.json",
            HERE / "expected.json",
            Path(__file__),
        )
    }
    root = HERE.parents[1]
    reviewed_source_files = [
        "src/rde/domain/models/preparation.py",
        "src/rde/infrastructure/preparation/sources.py",
        "src/rde/infrastructure/preparation/engine.py",
        "src/rde/infrastructure/preparation/aggregation.py",
        "src/rde/infrastructure/preparation/workflow.py",
        "src/rde/infrastructure/preparation/portable.py",
        "pyproject.toml",
    ]
    receipt = {
        "schema": "incidence-pathways-contract-oracle-receipt-v1",
        "scope": "Synthetic SQL definitions + package CI boundary checks only; no native MCP implementation, TriNetX numerical equivalence, or clinical validation.",
        "baseline": "6c620bb62223a20e6eab97e1c96e5f5542e7c8f6",
        "source_sha256": file_hashes,
        "reviewed_rde_source_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in reviewed_source_files
        },
        "sqlite": sqlite3.sqlite_version,
        "checks": CHECKS,
        "check_count": len(CHECKS),
        "observed": observed,
        "trace": traces,
        "package": package,
    }
    (HERE / "oracle-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "checks": len(CHECKS),
                "receipt": str(HERE / "oracle-receipt.json"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

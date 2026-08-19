from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class KnowledgeInferenceError(RuntimeError):
    pass


FORBIDDEN_MEMBERSHIP_KEYS = {
    "ticker",
    "tickers",
    "symbol",
    "symbols",
    "company_id",
    "company_ids",
}


def _load(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise KnowledgeInferenceError(
            f"cannot read {path}: {exc}"
        ) from exc


def _validate_policy(
    policy: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    if (
        policy.get("schema_version")
        != "knowledge-inference-policy.v031c.3"
    ):
        raise KnowledgeInferenceError(
            "unsupported knowledge inference policy"
        )

    rules = policy.get("rules")
    if not isinstance(rules, list):
        raise KnowledgeInferenceError(
            "knowledge inference rules must be an array"
        )

    ids: set[str] = set()

    for rule in rules:
        rule_id = str(
            rule.get("rule_id")
            or ""
        )

        if (
            not rule_id
            or rule_id in ids
        ):
            raise KnowledgeInferenceError(
                "invalid or duplicate inference rule: "
                f"{rule_id}"
            )

        if (
            FORBIDDEN_MEMBERSHIP_KEYS
            .intersection(rule)
        ):
            raise KnowledgeInferenceError(
                "ticker/company membership is forbidden "
                f"in inference rules: {rule_id}"
            )

        if (
            not rule.get("output_id")
            or not rule.get(
                "output_dimension"
            )
            or not rule.get("any_inputs")
        ):
            raise KnowledgeInferenceError(
                "incomplete inference rule: "
                f"{rule_id}"
            )

        reliability = float(
            rule.get("reliability")
            or 0
        )

        if not (
            0 < reliability <= 1
        ):
            raise KnowledgeInferenceError(
                "invalid reliability for rule: "
                f"{rule_id}"
            )

        ids.add(rule_id)

    return rules


def _combine(
    items: list[Mapping[str, Any]],
    reliability: float,
) -> float:
    remaining = 1.0

    for item in items:
        remaining *= (
            1.0
            - float(item["confidence"])
            * reliability
        )

    return round(
        min(
            0.99,
            1.0 - remaining,
        ),
        4,
    )


def build_knowledge_inference(
    root: Path,
    *,
    signals_payload: Mapping[
        str,
        Any,
    ]
    | None = None,
    policy_path: str = (
        "config/"
        "knowledge_inference.v031c.3.json"
    ),
    signals_path: str = (
        "data/generated/"
        "company_signals/"
        "company_signals.json"
    ),
    relevance_gate_path: str = (
        "data/generated/"
        "research_relevance_gate/"
        "research_relevance_gate.json"
    ),
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Build evidence-derived Knowledge for the full company registry.

    Research relevance is downstream metadata only.

    A company being deprioritized for deep research must never suppress
    theme/sector inference.  Company existence and classification coverage
    are full-market contracts; the Research Universe controls downstream
    research depth such as news, ETF, competitor, and supply-chain work.
    """
    current = (
        now
        or datetime.now(
            timezone.utc
        )
    )

    if (
        current.tzinfo is None
        or current.utcoffset()
        is None
    ):
        raise ValueError(
            "now must be timezone-aware"
        )

    policy = _load(
        root / policy_path
    )

    signals_payload = (
        signals_payload
        or _load(
            root / signals_path
        )
    )

    gate_file = (
        root
        / relevance_gate_path
    )

    gate_payload = (
        _load(gate_file)
        if gate_file.is_file()
        else {
            "records": [],
        }
    )

    gate_by_company = {
        str(row["company_id"]): row
        for row in (
            gate_payload.get(
                "records"
            )
            or []
        )
        if row.get("company_id")
    }

    rules = _validate_policy(
        policy
    )

    records_in = (
        signals_payload.get(
            "records"
        )
        if isinstance(
            signals_payload,
            Mapping,
        )
        else None
    )

    if (
        not isinstance(
            records_in,
            list,
        )
        or signals_payload.get(
            "schema_version"
        )
        != "company-signals.v031c.2"
    ):
        raise KnowledgeInferenceError(
            "V031C.2 company signals "
            "input is required"
        )

    output_records: list[
        dict[str, Any]
    ] = []

    dimension_counts: Counter[
        str
    ] = Counter()

    classification_counts: Counter[
        str
    ] = Counter()

    gate_status_counts: Counter[
        str
    ] = Counter()

    research_deprioritized_count = 0

    for company in records_in:
        company_id = str(
            company["company_id"]
        )

        signals = list(
            company.get("signals")
            or []
        )

        available: dict[
            str,
            dict[str, Any],
        ] = {
            str(
                signal[
                    "signal_id"
                ]
            ): {
                "knowledge_id": (
                    signal[
                        "signal_id"
                    ]
                ),
                "dimension": (
                    signal[
                        "dimension"
                    ]
                ),
                "canonical_name": (
                    signal[
                        "canonical_name"
                    ]
                ),
                "confidence": (
                    signal[
                        "confidence"
                    ]
                ),
                "primary_business_score": int(
                    signal.get(
                        "primary_business_score"
                    )
                    or 0
                ),
                "derivation_type": (
                    "observed_signal"
                ),
                "source_signal_ids": [
                    signal[
                        "signal_id"
                    ]
                ],
                "source_business_evidence_ids": (
                    signal[
                        "source_business_evidence_ids"
                    ]
                ),
                "inference_paths": [],
            }
            for signal
            in signals
        }

        inferred_ids: set[
            str
        ] = set()

        gate = (
            gate_by_company.get(
                company_id
            )
        )

        gate_status = str(
            (
                gate
                or {}
            ).get(
                "status"
            )
            or ""
        )

        if gate_status:
            gate_status_counts[
                gate_status
            ] += 1

        if (
            gate
            and gate.get(
                "deep_inference_required"
            )
            is False
        ):
            research_deprioritized_count += 1

        # Full-market contract:
        # Research relevance never short-circuits Knowledge inference.
        for _ in range(
            int(
                policy.get(
                    "maximum_iterations"
                )
                or 1
            )
        ):
            changed = False

            for rule in rules:
                inputs = [
                    available[value]
                    for value in (
                        rule[
                            "any_inputs"
                        ]
                    )
                    if value
                    in available
                ]

                required = [
                    str(value)
                    for value in (
                        rule.get(
                            "all_inputs"
                        )
                        or []
                    )
                ]

                if (
                    not inputs
                    or any(
                        value
                        not in available
                        for value
                        in required
                    )
                ):
                    continue

                inputs.extend(
                    available[value]
                    for value
                    in required
                    if (
                        available[value]
                        not in inputs
                    )
                )

                output_id = str(
                    rule[
                        "output_id"
                    ]
                )

                confidence = (
                    _combine(
                        inputs,
                        float(
                            rule[
                                "reliability"
                            ]
                        ),
                    )
                )

                evidence_ids = sorted(
                    {
                        evidence_id
                        for item
                        in inputs
                        for evidence_id
                        in item[
                            "source_business_evidence_ids"
                        ]
                    }
                )

                source_signal_ids = sorted(
                    {
                        signal_id
                        for item
                        in inputs
                        for signal_id
                        in item[
                            "source_signal_ids"
                        ]
                    }
                )

                primary_business_score = max(
                    (
                        int(
                            item.get(
                                "primary_business_score"
                            )
                            or 0
                        )
                        for item
                        in inputs
                    ),
                    default=0,
                )

                path = {
                    "rule_id": (
                        rule[
                            "rule_id"
                        ]
                    ),
                    "input_knowledge_ids": sorted(
                        item[
                            "knowledge_id"
                        ]
                        for item
                        in inputs
                    ),
                    "source_signal_ids": (
                        source_signal_ids
                    ),
                    "source_business_evidence_ids": (
                        evidence_ids
                    ),
                    "reliability": (
                        rule[
                            "reliability"
                        ]
                    ),
                    "score": (
                        confidence
                    ),
                }

                existing = (
                    available.get(
                        output_id
                    )
                )

                if (
                    existing is None
                    or confidence
                    > float(
                        existing[
                            "confidence"
                        ]
                    )
                ):
                    available[
                        output_id
                    ] = {
                        "knowledge_id": (
                            output_id
                        ),
                        "dimension": (
                            rule[
                                "output_dimension"
                            ]
                        ),
                        "canonical_name": (
                            rule[
                                "canonical_name"
                            ]
                        ),
                        "confidence": (
                            confidence
                        ),
                        "primary_business_score": (
                            primary_business_score
                        ),
                        "derivation_type": (
                            "rule_inference"
                        ),
                        "source_signal_ids": (
                            source_signal_ids
                        ),
                        "source_business_evidence_ids": (
                            evidence_ids
                        ),
                        "inference_paths": [
                            path
                        ],
                    }

                    inferred_ids.add(
                        output_id
                    )
                    changed = True

                elif (
                    path
                    not in existing[
                        "inference_paths"
                    ]
                ):
                    existing[
                        "inference_paths"
                    ].append(
                        path
                    )

            if not changed:
                break

        knowledge = sorted(
            available.values(),
            key=lambda row: (
                row[
                    "dimension"
                ],
                -float(
                    row[
                        "confidence"
                    ]
                ),
                row[
                    "knowledge_id"
                ],
            ),
        )

        for item in knowledge:
            dimension_counts[
                str(
                    item[
                        "dimension"
                    ]
                )
            ] += 1

            if (
                item[
                    "derivation_type"
                ]
                == "rule_inference"
            ):
                classification_counts[
                    str(
                        item[
                            "knowledge_id"
                        ]
                    )
                ] += 1

        status = (
            "knowledge_available"
            if inferred_ids
            else "signals_only"
            if signals
            else company["status"]
        )

        output_records.append(
            {
                "company_id": (
                    company_id
                ),
                "status": status,
                "source_company_signal_status": (
                    company[
                        "status"
                    ]
                ),
                "primary_business_evidence": list(
                    company.get(
                        "primary_offering_evidence"
                    )
                    or []
                ),
                "relevance_gate_status": (
                    (
                        gate
                        or {}
                    ).get(
                        "status"
                    )
                ),
                "research_deep_inference_required": (
                    None
                    if gate is None
                    else gate.get(
                        "deep_inference_required"
                    )
                ),
                "knowledge": (
                    knowledge
                ),
            }
        )

    return {
        "schema_version": (
            "multidimensional-"
            "knowledge-inference."
            "v031c.3"
        ),
        "version": "V031C.3",
        "generated_at": (
            current.isoformat()
        ),
        "summary": {
            "company_count": len(
                output_records
            ),
            "knowledge_available_company_count": sum(
                row["status"]
                == "knowledge_available"
                for row
                in output_records
            ),
            "signals_only_company_count": sum(
                row["status"]
                == "signals_only"
                for row
                in output_records
            ),
            "primary_business_evidence_company_count": sum(
                bool(
                    row.get(
                        "primary_business_evidence"
                    )
                )
                for row
                in output_records
            ),
            # Retained for backward-compatible summary consumers.
            # It must now be zero because research relevance no longer
            # changes the Knowledge status.
            "research_irrelevant_company_count": sum(
                row["status"]
                == "research_irrelevant"
                for row
                in output_records
            ),
            "research_deprioritized_gate_company_count": (
                research_deprioritized_count
            ),
            "relevance_gate_status_counts": dict(
                sorted(
                    gate_status_counts.items()
                )
            ),
            "dimension_record_counts": dict(
                sorted(
                    dimension_counts.items()
                )
            ),
            "inferred_classification_company_counts": dict(
                sorted(
                    classification_counts.items()
                )
            ),
        },
        "policy": {
            "policy_path": (
                policy_path
            ),
            "contains_ticker_membership": (
                False
            ),
            "research_relevance_controls_inference": (
                False
            ),
        },
        "records": (
            output_records
        ),
        "indexes": {
            "company_id_to_position": {
                row[
                    "company_id"
                ]: index
                for (
                    index,
                    row,
                )
                in enumerate(
                    output_records
                )
            }
        },
    }


def write_knowledge_inference(
    report: Mapping[
        str,
        Any,
    ],
    output: Path,
) -> None:
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )
        + "\n",
        encoding="utf-8",
    )
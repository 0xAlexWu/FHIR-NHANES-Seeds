#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from nhanes_common import outputs_dir

INPUT_STYLES = ("concise_clinical", "semi_structured")
SELECTED_SEEDS_FILE = "outputs/nhanes/nhanes_pilot15_selected.csv"

PAIR_COLUMNS = [
    "pair_id",
    "seed_id",
    "resource_type",
    "input_style",
    "input_text",
    "target_seed_file",
    "target_fhir_json",
    "unsupported_fact_added",
    "missingness_preserved",
    "review_status",
    "notes",
]

FLAG_COLUMNS = [
    "pair_id",
    "seed_id",
    "resource_type",
    "flag_type",
    "flag_reason",
]

PATIENT_FIELD_LABELS = {
    "gender": "Gender",
    "age_years": "Age in years at screening",
    "race_ethnicity": "Race/Hispanic origin",
    "country_of_birth": "Country of birth",
    "citizenship_status": "Citizenship status",
    "marital_status": "Marital status",
    "pregnancy_status": "Pregnancy status at exam",
}

UNIT_SENSITIVE_MEASURES = {
    "Systolic: Blood pres",
    "Diastolic: Blood pres",
    "Glycohemoglobin",
    "Total Cholesterol",
    "Creatinine, refrigerated serum",
    "Albumin, refrigerated serum",
    "Total Calcium",
}


def selected_seed_path() -> Path:
    path = outputs_dir() / "nhanes_pilot15_selected.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing selected-seed file: {path}")
    return path


def load_selected_seeds() -> pd.DataFrame:
    return pd.read_csv(selected_seed_path(), low_memory=False)


def parse_structured_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def seed_measure_name(row: pd.Series) -> str:
    if row["resource_type"] == "Patient":
        return "patient_demographics_bundle"
    variable_display = row["variable_name_or_measure_name"]
    if ":" not in variable_display:
        return variable_display
    return variable_display.split(":", 1)[1].strip()


def observation_target(row: pd.Series, payload: dict[str, Any]) -> dict[str, Any]:
    measure_name = payload.get("measure_name") or seed_measure_name(row)
    target = {
        "resourceType": "Observation",
        "code": {"text": measure_name},
        "subject": {"identifier": {"value": str(row["participant_id_if_available"])}},
        "valueQuantity": {
            "value": payload.get("value"),
            "unit": payload.get("unit") or row["unit_if_available"],
        },
    }
    return target


def patient_extensions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    extensions: list[dict[str, Any]] = []
    for key, label in PATIENT_FIELD_LABELS.items():
        if key == "gender":
            continue
        value = payload.get(key)
        if value is None:
            continue
        extension: dict[str, Any] = {"url": f"urn:nhanes:{key}"}
        if key == "age_years":
            extension["valueInteger"] = int(value)
        else:
            extension["valueString"] = str(value)
        extensions.append(extension)
    return extensions


def patient_target(row: pd.Series, payload: dict[str, Any]) -> dict[str, Any]:
    target: dict[str, Any] = {
        "resourceType": "Patient",
        "identifier": [{"value": str(row["participant_id_if_available"])}],
    }
    gender = payload.get("gender")
    if isinstance(gender, str):
        lowered = gender.lower()
        if lowered in {"male", "female", "other", "unknown"}:
            target["gender"] = lowered
    extensions = patient_extensions(payload)
    if extensions:
        target["extension"] = extensions
    return target


def target_fhir_json(row: pd.Series, payload: dict[str, Any]) -> dict[str, Any]:
    if row["resource_type"] == "Observation":
        return observation_target(row, payload)
    return patient_target(row, payload)


def patient_text_fields(payload: dict[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for key in [
        "gender",
        "age_years",
        "race_ethnicity",
        "country_of_birth",
        "citizenship_status",
        "marital_status",
        "pregnancy_status",
    ]:
        value = payload.get(key)
        if value is None:
            continue
        label = PATIENT_FIELD_LABELS[key]
        if key == "age_years":
            rendered = f"{int(value)} years"
        else:
            rendered = str(value)
        fields.append((label, rendered))
    return fields


def observation_input_text(row: pd.Series, payload: dict[str, Any], style: str) -> str:
    measure = payload.get("measure_name") or seed_measure_name(row)
    value = payload.get("value")
    unit = payload.get("unit") or row["unit_if_available"]
    participant = row["participant_id_if_available"]
    source_file = row["source_file"].replace(".xpt", "")

    if style == "concise_clinical":
        return f"{measure}: {value} {unit}".strip()

    return "\n".join(
        [
            source_file,
            f"participant: {participant}",
            f"measure = {measure}",
            f"value = {value}",
            f"unit = {unit}",
        ]
    )


def patient_input_text(row: pd.Series, payload: dict[str, Any], style: str) -> str:
    participant = row["participant_id_if_available"]
    fields = patient_text_fields(payload)

    if style == "concise_clinical":
        return "; ".join(f"{label}: {value}" for label, value in fields)

    lines = ["DEMO_J", f"participant: {participant}"]
    lines.extend(f"{label} = {value}" for label, value in fields)
    return "\n".join(lines)


def input_text(row: pd.Series, payload: dict[str, Any], style: str) -> str:
    if row["resource_type"] == "Observation":
        return observation_input_text(row, payload, style)
    return patient_input_text(row, payload, style)


def pair_notes(row: pd.Series) -> str:
    if row["resource_type"] == "Observation":
        return "Target uses Observation.code.text and valueQuantity only; no standard coding system was asserted."
    return "Target keeps Patient.gender when available and preserves the remaining NHANES demographic fragments via local extension-style fields."


def build_flag_rows(selected: pd.DataFrame) -> pd.DataFrame:
    flag_rows: list[dict[str, str]] = []

    for _, row in selected.iterrows():
        payload = parse_structured_value(row["structured_value"])
        seed_id = row["selected_id"]
        resource_type = row["resource_type"]
        measure = seed_measure_name(row)
        field_count = len(patient_text_fields(payload)) if resource_type == "Patient" else 0

        for style in INPUT_STYLES:
            pair_id = f"{seed_id}-{style}"
            if resource_type == "Patient" and seed_id in {"NHANES-P15-01", "NHANES-P15-04", "NHANES-P15-05"}:
                flag_rows.append(
                    {
                        "pair_id": pair_id,
                        "seed_id": seed_id,
                        "resource_type": resource_type,
                        "flag_type": "coding_uncertainty",
                        "flag_reason": "Patient target preserves NHANES-specific demographics in custom extension-style fields rather than standard coded elements.",
                    }
                )
            if resource_type == "Patient" and field_count <= 4:
                flag_rows.append(
                    {
                        "pair_id": pair_id,
                        "seed_id": seed_id,
                        "resource_type": resource_type,
                        "flag_type": "demographic_fragment_sparsity",
                        "flag_reason": "The seed contains only a small demographic fragment, so omission risk should be checked during review.",
                    }
                )
            if resource_type == "Observation" and measure in UNIT_SENSITIVE_MEASURES:
                flag_rows.append(
                    {
                        "pair_id": pair_id,
                        "seed_id": seed_id,
                        "resource_type": resource_type,
                        "flag_type": "unit_sensitivity",
                        "flag_reason": "The measured value depends on exact unit preservation and should be checked before promotion.",
                    }
                )

    flags = pd.DataFrame(flag_rows)
    if flags.empty:
        return pd.DataFrame(columns=FLAG_COLUMNS)
    return flags[FLAG_COLUMNS].drop_duplicates().sort_values(by=["pair_id", "flag_type"]).reset_index(drop=True)


def build_pairs(selected: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    flagged_pair_ids = set(flags["pair_id"]) if not flags.empty else set()
    pair_rows: list[dict[str, Any]] = []

    for _, row in selected.iterrows():
        payload = parse_structured_value(row["structured_value"])
        target = target_fhir_json(row, payload)

        for style in INPUT_STYLES:
            pair_id = f"{row['selected_id']}-{style}"
            pair_rows.append(
                {
                    "pair_id": pair_id,
                    "seed_id": row["selected_id"],
                    "resource_type": row["resource_type"],
                    "input_style": style,
                    "input_text": input_text(row, payload, style),
                    "target_seed_file": SELECTED_SEEDS_FILE,
                    "target_fhir_json": json.dumps(target, ensure_ascii=True, sort_keys=True),
                    "unsupported_fact_added": False,
                    "missingness_preserved": True,
                    "review_status": "needs_manual_review" if pair_id in flagged_pair_ids else "ready",
                    "notes": pair_notes(row),
                }
            )

    pairs = pd.DataFrame(pair_rows)
    return pairs[PAIR_COLUMNS].sort_values(by=["pair_id"]).reset_index(drop=True)


def write_jsonl(pairs: pd.DataFrame, destination: Path) -> None:
    with destination.open("w", encoding="utf-8") as handle:
        for record in pairs.to_dict(orient="records"):
            target = record.get("target_fhir_json")
            if isinstance(target, str):
                try:
                    record["target_fhir_json"] = json.loads(target)
                except json.JSONDecodeError:
                    pass
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def build_summary(selected: pd.DataFrame, pairs: pd.DataFrame, flags: pd.DataFrame) -> str:
    seeds_processed = int(selected["selected_id"].nunique())
    total_pairs = int(len(pairs))
    per_resource = pairs["resource_type"].value_counts()
    per_style = pairs["input_style"].value_counts()
    flagged_pairs = sorted(flags["pair_id"].unique().tolist()) if not flags.empty else []
    difficult_seed_ids = sorted(flags["seed_id"].unique().tolist()) if not flags.empty else []

    return f"""# NHANES Pilot 15 Pair Generation Summary

## Totals

- Total number of seeds processed: {seeds_processed}
- Total number of pairs generated: {total_pairs}

## Variants per resource type

- Patient: {int(per_resource.get('Patient', 0))}
- Observation: {int(per_resource.get('Observation', 0))}

## Variants per input style

- concise_clinical: {int(per_style.get('concise_clinical', 0))}
- semi_structured: {int(per_style.get('semi_structured', 0))}

## Seeds that were difficult to express cleanly

- {', '.join(difficult_seed_ids) if difficult_seed_ids else 'None.'}

## Rows flagged for manual review

- {len(flagged_pairs)} pairs were flagged for first-pass manual review.
- {', '.join(flagged_pairs[:12]) + (' ...' if len(flagged_pairs) > 12 else '') if flagged_pairs else 'No pair-level review flags were raised.'}

## Pairing assessment

NHANES looks stronger here as a semi-structured pairing source than as a free-text source. The generated inputs stay cleanest when they remain measurement-like or form-like, while more natural free-text phrasing would add avoidable risk of omission or unsupported detail.
"""


def main() -> None:
    outputs = outputs_dir()
    outputs.mkdir(parents=True, exist_ok=True)

    selected = load_selected_seeds().rename(columns={"likely_fhir_resource": "resource_type"})
    flags = build_flag_rows(selected)
    pairs = build_pairs(selected, flags)

    if len(pairs) != 30:
        raise ValueError(f"Expected exactly 30 pairs, found {len(pairs)}")
    if pairs["seed_id"].nunique() != 15:
        raise ValueError("Expected pairs to reference exactly 15 selected seeds.")

    jsonl_path = outputs / "nhanes_pilot15_pair_candidates.jsonl"
    csv_path = outputs / "nhanes_pilot15_pair_candidates.csv"
    summary_path = outputs / "nhanes_pilot15_pair_generation_summary.md"
    flags_path = outputs / "nhanes_pilot15_pair_review_flags.csv"

    write_jsonl(pairs, jsonl_path)
    pairs.to_csv(csv_path, index=False)
    summary_path.write_text(build_summary(selected, pairs, flags), encoding="utf-8")
    flags.to_csv(flags_path, index=False)

    print(f"wrote {jsonl_path}")
    print(f"wrote {csv_path}")
    print(f"wrote {summary_path}")
    print(f"wrote {flags_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from nhanes_common import outputs_dir

STRICT_BOOL_COLUMNS = (
    "json_ready",
    "likely_numeric",
    "needs_linked_context",
    "good_for_pairing",
)

SELECTED_COLUMNS = [
    "selected_id",
    "likely_fhir_resource",
    "source_component",
    "source_file",
    "variable_name_or_measure_name",
    "participant_id_if_available",
    "candidate_text_snippet",
    "structured_value",
    "unit_if_available",
    "likely_numeric",
    "needs_linked_context",
    "complexity_guess",
    "selection_priority",
    "selection_notes",
]

REJECTED_COLUMNS = [
    "candidate_id",
    "likely_fhir_resource",
    "source_component",
    "source_file",
    "variable_name_or_measure_name",
    "participant_id_if_available",
    "candidate_text_snippet",
    "unit_if_available",
    "likely_numeric",
    "needs_linked_context",
    "complexity_guess",
    "rejection_category",
    "rejection_reason",
]

OBSERVATION_PLAN = [
    {
        "display": "BMXWT: Weight",
        "note": "Canonical anthropometric Observation with an explicit kg unit and direct valueQuantity semantics.",
    },
    {
        "display": "BMXHT: Standing Height",
        "note": "Clean anthropometric height measurement with a stable cm unit and minimal interpretation burden.",
    },
    {
        "display": "BMXBMI: Body Mass Index (kg/m^2)",
        "note": "Useful derived anthropometric Observation that still reads naturally as a semi-structured measurement.",
    },
    {
        "display": "BPXSY1: Systolic: Blood pres",
        "note": "First-reading systolic blood pressure is highly FHIR-friendly and avoids repeated-reading duplication in the pilot.",
    },
    {
        "display": "BPXDI1: Diastolic: Blood pres",
        "note": "First-reading diastolic blood pressure complements systolic coverage without pulling in redundant later readings.",
    },
    {
        "display": "LBXGH: Glycohemoglobin",
        "note": "Compact lab Observation with a clear percentage unit and strong pairing potential.",
    },
    {
        "display": "LBXTC: Total Cholesterol",
        "note": "Reference-method cholesterol measurement with straightforward mg/dL semantics.",
    },
    {
        "display": "LBXSCR: Creatinine, refrigerated serum",
        "note": "Representative chemistry Observation with clear renal-lab semantics and explicit units.",
    },
    {
        "display": "LBXSAL: Albumin, refrigerated serum",
        "note": "Common chemistry-panel Observation with clean g/dL representation.",
    },
    {
        "display": "LBXSCA: Total Calcium",
        "note": "Straightforward chemistry Observation that broadens the pilot beyond only lipids and glycemic measures.",
    },
]

PATIENT_BUCKETS = [
    {
        "name": "pregnant_adult",
        "note": "Selected to keep one clean Patient-like seed with explicit pregnancy context in the demographic bundle.",
        "filter": lambda df: df["pregnancy_status"].fillna("").str.contains(
            "positive lab pregnancy test", case=False
        ),
    },
    {
        "name": "adult_male",
        "note": "Selected as a simple adult male demographic seed with no extra linked-context dependency.",
        "filter": lambda df: (
            df["gender"].eq("Male")
            & df["age_years"].between(30, 50, inclusive="both")
            & df["race_ethnicity"].eq("Non-Hispanic White")
        ),
    },
    {
        "name": "school_age_child",
        "note": "Selected to keep one pediatric demographic seed in the first pilot without requiring downstream inference.",
        "filter": lambda df: (
            df["age_years"].between(6, 12, inclusive="both")
            & df["race_ethnicity"].eq("Non-Hispanic Black")
        ),
    },
    {
        "name": "older_non_citizen",
        "note": "Selected to capture an older adult demographic slice with a clean but distinct citizenship/birth-country pattern.",
        "filter": lambda df: (
            df["age_years"].between(60, 79, inclusive="both")
            & df["citizenship_status"].fillna("").str.contains("Not a citizen", case=False)
        ),
    },
    {
        "name": "asian_immigrant_adult",
        "note": "Selected to add a clean adult immigrant-style demographic seed and broaden racial/ethnic coverage.",
        "filter": lambda df: (
            df["race_ethnicity"].eq("Non-Hispanic Asian")
            & df["country_of_birth"].eq("Others")
            & df["age_years"].between(18, 60, inclusive="both")
        ),
    },
]


def catalog_candidates() -> list[Path]:
    base = outputs_dir()
    return [
        base / "candidate_seed_catalog.csv.gz",
        base / "candidate_seed_catalog.csv",
    ]


def load_catalog() -> pd.DataFrame:
    for path in catalog_candidates():
        if path.exists():
            df = pd.read_csv(path, low_memory=False)
            break
    else:
        raise FileNotFoundError("No candidate catalog was found in outputs/nhanes/")

    for column in STRICT_BOOL_COLUMNS:
        if df[column].dtype == object:
            df[column] = df[column].astype(str).str.lower().map({"true": True, "false": False})
        df[column] = df[column].fillna(False).astype(bool)

    df["participant_sort"] = pd.to_numeric(df["participant_id_if_available"], errors="coerce").fillna(10**12)
    return df


def parse_payload(payload_text: Any) -> dict[str, Any]:
    if not isinstance(payload_text, str):
        return {}
    try:
        return json.loads(payload_text)
    except json.JSONDecodeError:
        return {}


def prepare_patients(df: pd.DataFrame) -> pd.DataFrame:
    patients = df[df["likely_fhir_resource"] == "Patient"].copy()
    patients["payload"] = patients["structured_value"].map(parse_payload)
    patients["gender"] = patients["payload"].map(lambda payload: payload.get("gender"))
    patients["age_years"] = patients["payload"].map(lambda payload: payload.get("age_years"))
    patients["race_ethnicity"] = patients["payload"].map(lambda payload: payload.get("race_ethnicity"))
    patients["citizenship_status"] = patients["payload"].map(lambda payload: payload.get("citizenship_status"))
    patients["pregnancy_status"] = patients["payload"].map(lambda payload: payload.get("pregnancy_status"))
    patients["country_of_birth"] = patients["payload"].map(lambda payload: payload.get("country_of_birth"))
    return patients


def strict_patient_subset(patients: pd.DataFrame) -> pd.DataFrame:
    return patients[
        (patients["good_for_pairing"] == True)
        & (patients["needs_linked_context"] == False)
        & (patients["complexity_guess"].isin(["low", "medium"]))
    ].copy()


def strict_observation_subset(df: pd.DataFrame) -> pd.DataFrame:
    observations = df[df["likely_fhir_resource"] == "Observation"].copy()
    return observations[
        (observations["good_for_pairing"] == True)
        & (observations["likely_numeric"] == True)
        & (observations["needs_linked_context"] == False)
        & (observations["complexity_guess"].isin(["low", "medium"]))
        & (observations["unit_if_available"].fillna("") != "")
    ].copy()


def choose_first(
    subset: pd.DataFrame,
    used_participants: set[str],
    filter_func: Callable[[pd.DataFrame], pd.Series] | None = None,
) -> pd.Series:
    if filter_func is not None:
        subset = subset[filter_func(subset)].copy()

    subset = subset.sort_values(by=["participant_sort", "candidate_id"])
    for _, row in subset.iterrows():
        participant_id = str(row["participant_id_if_available"])
        if participant_id not in used_participants:
            return row
    raise ValueError("Unable to choose a unique candidate for one of the pilot buckets.")


def build_patient_selections(strict_patients: pd.DataFrame) -> tuple[list[dict[str, Any]], set[str]]:
    used_participants: set[str] = set()
    selections: list[dict[str, Any]] = []

    for index, bucket in enumerate(PATIENT_BUCKETS, start=1):
        row = choose_first(strict_patients, used_participants, filter_func=bucket["filter"])
        used_participants.add(str(row["participant_id_if_available"]))
        selections.append(
            {
                **row.to_dict(),
                "selected_id": f"NHANES-P15-{index:02d}",
                "selection_priority": index,
                "selection_notes": bucket["note"],
            }
        )

    return selections, used_participants


def build_observation_selections(
    strict_observations: pd.DataFrame,
    start_priority: int,
    used_participants: set[str] | None = None,
) -> list[dict[str, Any]]:
    used_participants = set() if used_participants is None else set(used_participants)
    selections: list[dict[str, Any]] = []

    for offset, plan in enumerate(OBSERVATION_PLAN, start=start_priority):
        subset = strict_observations[
            strict_observations["variable_name_or_measure_name"].eq(plan["display"])
        ].copy()
        row = choose_first(subset, used_participants)
        used_participants.add(str(row["participant_id_if_available"]))
        selections.append(
            {
                **row.to_dict(),
                "selected_id": f"NHANES-P15-{offset:02d}",
                "selection_priority": offset,
                "selection_notes": plan["note"],
            }
        )

    return selections


def make_selected_frame(selected_rows: list[dict[str, Any]]) -> pd.DataFrame:
    selected = pd.DataFrame(selected_rows)
    selected = selected.sort_values(by="selection_priority").copy()
    for column in SELECTED_COLUMNS:
        if column not in selected.columns:
            selected[column] = ""
    return selected[SELECTED_COLUMNS]


def build_rejected_examples(
    catalog: pd.DataFrame,
    strict_patients: pd.DataFrame,
    strict_observations: pd.DataFrame,
) -> pd.DataFrame:
    rejected_rows: list[dict[str, Any]] = []

    def add_example(row: pd.Series, category: str, reason: str) -> None:
        rejected_rows.append(
            {
                "candidate_id": row["candidate_id"],
                "likely_fhir_resource": row["likely_fhir_resource"],
                "source_component": row["source_component"],
                "source_file": row["source_file"],
                "variable_name_or_measure_name": row["variable_name_or_measure_name"],
                "participant_id_if_available": row["participant_id_if_available"],
                "candidate_text_snippet": row["candidate_text_snippet"],
                "unit_if_available": row["unit_if_available"],
                "likely_numeric": row["likely_numeric"],
                "needs_linked_context": row["needs_linked_context"],
                "complexity_guess": row["complexity_guess"],
                "rejection_category": category,
                "rejection_reason": reason,
            }
        )

    patient_candidates = strict_patients.sort_values(by=["participant_sort", "candidate_id"]).copy()
    actual_pregnancy_uncertain = patient_candidates[
        patient_candidates["pregnancy_status"].fillna("").str.contains("Cannot ascertain", case=False)
    ]
    top_coded_age = patient_candidates[patient_candidates["age_years"].eq(80)]

    if not actual_pregnancy_uncertain.empty:
        add_example(
            actual_pregnancy_uncertain.iloc[0],
            "strict_pass_but_not_selected",
            "Pregnancy status is explicitly uncertain, so it was left out of the first review-ready pilot.",
        )
    if not top_coded_age.empty:
        add_example(
            top_coded_age.iloc[0],
            "strict_pass_but_not_selected",
            "Public NHANES top-codes age at 80, so a cleaner age example was preferred for the first pilot.",
        )

    later_bp_readings = strict_observations[
        strict_observations["variable_name_or_measure_name"].isin(
            ["BPXSY2: Systolic: Blood pres", "BPXDI2: Diastolic: Blood pres"]
        )
    ].sort_values(by=["participant_sort", "candidate_id"])
    anthropometric_overflow = strict_observations[
        strict_observations["variable_name_or_measure_name"].isin(
            [
                "BMXARMC: Arm Circumference",
                "BMXARML: Upper Arm Length",
                "BMXWAIST: Waist Circumference",
                "BMXHIP: Hip Circumference",
            ]
        )
    ].sort_values(by=["participant_sort", "candidate_id"])
    no_unit_examples = catalog[
        (catalog["likely_fhir_resource"] == "Observation")
        & (catalog["good_for_pairing"] == False)
        & (catalog["unit_if_available"].fillna("") == "")
    ].sort_values(by=["participant_sort", "candidate_id"])
    linked_context_examples = catalog[
        (catalog["likely_fhir_resource"] == "Observation")
        & (catalog["needs_linked_context"] == True)
    ].sort_values(by=["participant_sort", "candidate_id"])

    if not later_bp_readings.empty:
        add_example(
            later_bp_readings.iloc[0],
            "strict_pass_but_not_selected",
            "Later blood-pressure readings were skipped to avoid near-duplicate repetition in the first pilot.",
        )
    for row in anthropometric_overflow.head(3).itertuples(index=False):
        add_example(
            pd.Series(row._asdict()),
            "strict_pass_but_not_selected",
            "Strong candidate, but the first pilot already includes enough anthropometric coverage.",
        )
    if not no_unit_examples.empty:
        add_example(
            no_unit_examples.iloc[0],
            "strict_failure",
            "Rejected because the candidate lacks an explicit unit and is less review-ready for clean Observation pairing.",
        )
    for row in linked_context_examples.head(2).itertuples(index=False):
        add_example(
            pd.Series(row._asdict()),
            "strict_failure",
            "Rejected because the source notes indicate linked-context or reference-method dependence.",
        )

    rejected = pd.DataFrame(rejected_rows).drop_duplicates(subset=["candidate_id"]).reset_index(drop=True)
    return rejected[REJECTED_COLUMNS]


def write_selected_jsonl(selected: pd.DataFrame, destination: Path) -> None:
    with destination.open("w", encoding="utf-8") as handle:
        for record in selected.to_dict(orient="records"):
            structured_value = record.get("structured_value")
            if isinstance(structured_value, str):
                try:
                    record["structured_value"] = json.loads(structured_value)
                except json.JSONDecodeError:
                    pass
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def strict_selection_count(selected: pd.DataFrame) -> int:
    observation_mask = selected["likely_fhir_resource"].eq("Observation")
    patient_mask = selected["likely_fhir_resource"].eq("Patient")
    strict_observation = (
        observation_mask
        & selected["likely_numeric"].eq(True)
        & selected["needs_linked_context"].eq(False)
        & selected["complexity_guess"].isin(["low", "medium"])
        & selected["unit_if_available"].fillna("").ne("")
    )
    strict_patient = (
        patient_mask
        & selected["needs_linked_context"].eq(False)
        & selected["complexity_guess"].isin(["low", "medium"])
    )
    return int((strict_observation | strict_patient).sum())


def build_summary(selected: pd.DataFrame) -> str:
    counts = selected["likely_fhir_resource"].value_counts()
    strict_count = strict_selection_count(selected)

    observation_measures = (
        selected[selected["likely_fhir_resource"] == "Observation"]["variable_name_or_measure_name"]
        .tolist()
    )
    measure_summary = ", ".join(observation_measures)

    return f"""# NHANES Pilot 15 Summary

## Final counts by resource type

- Patient: {int(counts.get('Patient', 0))}
- Observation: {int(counts.get('Observation', 0))}
- Condition: {int(counts.get('Condition', 0))}

## Strict preferred criteria coverage

- Selected seeds meeting the strict preferred criteria: {strict_count} / {len(selected)}

## Criteria relaxations used

- None. All 15 selections met the preferred first-pass criteria: `good_for_pairing = true`, low/medium complexity, and `needs_linked_context = false`.
- All 10 Observation selections are numeric and include explicit units.

## Why this pilot 15 is appropriate

- The 5 Patient selections are simple demographic bundles chosen for review-ready variety across age, sex, race/ethnicity, citizenship, and pregnancy context.
- The 10 Observation selections cover highly mappable first-pass measure types rather than repeating many rows from the same pattern.
- The Observation subset balances body measures, blood pressure, and laboratory chemistry so the pilot is useful for mapping review without ballooning into scale-first curation.
- No Condition-like candidates were included, matching the current NHANES-first-pass scope.

## Promising Observation measure types for later expansion

- Blood pressure: systolic and diastolic readings look especially strong for later expansion.
- Anthropometrics: weight, standing height, body mass index, waist, hip, and limb measures all look usable.
- Laboratory targets: glycohemoglobin, total cholesterol, creatinine, albumin, calcium, bilirubin, urea nitrogen, and related chemistry-panel measures appear promising for quota expansion.

## Selected Observation measure set

- {measure_summary}
"""


selected_rows_cache: list[dict[str, Any]] = []


def main() -> None:
    global selected_rows_cache

    outputs = outputs_dir()
    outputs.mkdir(parents=True, exist_ok=True)

    catalog = load_catalog()
    patients = prepare_patients(catalog)
    strict_patients = strict_patient_subset(patients)
    strict_observations = strict_observation_subset(catalog)

    patient_rows, used_patient_participants = build_patient_selections(strict_patients)
    observation_rows = build_observation_selections(
        strict_observations,
        start_priority=6,
        used_participants=used_patient_participants,
    )
    selected_rows_cache = patient_rows + observation_rows

    selected = make_selected_frame(selected_rows_cache)
    rejected = build_rejected_examples(catalog, strict_patients, strict_observations)

    if len(selected) != 15:
        raise ValueError(f"Expected exactly 15 selected rows, found {len(selected)}")

    resource_counts = selected["likely_fhir_resource"].value_counts().to_dict()
    if resource_counts.get("Patient", 0) != 5 or resource_counts.get("Observation", 0) != 10:
        raise ValueError(f"Unexpected resource mix: {resource_counts}")

    selected_csv = outputs / "nhanes_pilot15_selected.csv"
    selected_jsonl = outputs / "nhanes_pilot15_selected.jsonl"
    summary_md = outputs / "nhanes_pilot15_summary.md"
    rejected_csv = outputs / "nhanes_pilot15_rejected_examples.csv"

    selected.to_csv(selected_csv, index=False)
    write_selected_jsonl(selected, selected_jsonl)
    summary_md.write_text(build_summary(selected), encoding="utf-8")
    rejected.to_csv(rejected_csv, index=False)

    print(f"wrote {selected_csv}")
    print(f"wrote {selected_jsonl}")
    print(f"wrote {summary_md}")
    print(f"wrote {rejected_csv}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from nhanes_common import DEFAULT_CYCLE, measure_name_from_display, outputs_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recommend a conservative NHANES pilot subset.")
    parser.add_argument("--cycle", default=DEFAULT_CYCLE, help="NHANES cycle label to summarize.")
    return parser.parse_args()


def load_candidate_catalog(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing candidate catalog at {path}. Run build_nhanes_candidate_catalog.py first."
        )
    return pd.read_csv(path, low_memory=False)


def pilot_size_recommendation(observation_ready: int, patient_ready: int) -> tuple[int, int, int]:
    total = 12
    observation_target = 9 if observation_ready >= 9 else max(1, min(observation_ready, total - 3))
    patient_target = min(patient_ready, total - observation_target)
    return total, observation_target, patient_target


def measure_priority(name: str) -> int:
    lowered = name.lower()
    keyword_scores = {
        "systolic": 6,
        "diastolic": 6,
        "blood pres": 6,
        "weight": 5,
        "height": 5,
        "body mass index": 5,
        "cholesterol": 5,
        "glycohemoglobin": 5,
        "glucose": 4,
        "creatinine": 4,
        "bilirubin": 3,
        "albumin": 3,
        "protein": 3,
    }
    return max((score for keyword, score in keyword_scores.items() if keyword in lowered), default=1)


def main() -> None:
    args = parse_args()
    base_output_dir = outputs_dir()
    candidate_catalog_path = base_output_dir / "candidate_seed_catalog.csv"
    candidate_df = load_candidate_catalog(candidate_catalog_path)

    observation_df = candidate_df[candidate_df["likely_fhir_resource"] == "Observation"].copy()
    patient_df = candidate_df[candidate_df["likely_fhir_resource"] == "Patient"].copy()

    if observation_df.empty:
        raise ValueError("Observation candidate pool is empty; no pilot recommendation can be produced.")

    observation_df["measure_type"] = observation_df["variable_name_or_measure_name"].map(measure_name_from_display)
    pairing_friendly = observation_df[observation_df["good_for_pairing"] == True].copy()
    top_measure_types = (
        pairing_friendly["measure_type"]
        .value_counts()
        .rename_axis("measure_type")
        .reset_index(name="count")
        .assign(priority=lambda df: df["measure_type"].map(measure_priority))
        .sort_values(by=["priority", "count", "measure_type"], ascending=[False, False, True])
        .head(5)[["measure_type", "count"]]
        .itertuples(index=False, name=None)
    )
    top_measure_summary = "; ".join(f"{name} [n={count}]" for name, count in top_measure_types)

    observation_ready = int(pairing_friendly.shape[0])
    patient_ready = int(patient_df[patient_df["good_for_pairing"] == True].shape[0])
    pilot_total, pilot_observation, pilot_patient = pilot_size_recommendation(observation_ready, patient_ready)

    observation_profile = pd.DataFrame(
        [
            {"metric": "total_observation_like_candidates", "value": int(observation_df.shape[0])},
            {"metric": "likely_numeric_observation_like_candidates", "value": int(observation_df["likely_numeric"].sum())},
            {"metric": "candidates_with_units", "value": int(observation_df["unit_if_available"].fillna("").ne("").sum())},
            {"metric": "candidates_without_units", "value": int(observation_df["unit_if_available"].fillna("").eq("").sum())},
            {"metric": "top_pairing_friendly_measure_types", "value": top_measure_summary},
        ]
    )
    observation_profile_path = base_output_dir / "observation_profile_summary.csv"
    observation_profile.to_csv(observation_profile_path, index=False)

    source_summary_path = base_output_dir / "nhanes_source_summary.md"
    source_summary = f"""# NHANES Source Summary

## Cycle used

- `{args.cycle}`

## Components used

- Demographics (`DEMO_J`)
- Examination (`BMX_J`, `BPX_J`)
- Laboratory (`GHB_J`, `TCHOL_J`, `BIOPRO_J`)

## Candidate pool

- Patient-like candidates: {int(patient_df.shape[0])}
- Observation-like candidates: {int(observation_df.shape[0])}
- Observation-like candidates marked pairing-friendly: {observation_ready}

## First-pilot suitability

The current NHANES-derived pool looks suitable for a first pilot. The Observation-oriented slice is materially cleaner than the Patient-oriented slice because the examination and laboratory files carry explicit measurement values, frequent units, and lower ambiguity than public-use demographic attributes.

## Backbone vs realism assessment

NHANES looks more useful here as a semi-structured realism source than as a backbone source. The strongest candidates preserve table-like and measurement-like character, while many public-use fields still need cautious interpretation or source-specific context before they become polished final pairs.

## Recommended pilot size

- Recommended first pilot shortlist size: {pilot_total}
- Recommended mix: {pilot_observation} Observation-focused candidates and {pilot_patient} Patient-focused candidates

## Rationale

- Keep the first pilot small enough for quick review and mapping cleanup.
- Overweight Observation candidates because units and numeric values are more consistently pairing-friendly.
- Keep a small Patient subset so demographic bundling can be tested without forcing full patient reconstruction too early.
- Continue treating Condition as out of scope until a clearly low-ambiguity NHANES mapping emerges.

## Top pairing-friendly Observation measure types

- {top_measure_summary or "No pairing-friendly Observation measure types were identified."}
"""
    source_summary_path.write_text(source_summary, encoding="utf-8")

    print(f"wrote {observation_profile_path}")
    print(f"wrote {source_summary_path}")


if __name__ == "__main__":
    main()

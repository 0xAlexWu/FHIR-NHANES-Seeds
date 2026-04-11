#!/usr/bin/env python3
from __future__ import annotations

import argparse

import pandas as pd

from nhanes_common import DEFAULT_CYCLE, collect_cycle_artifacts, outputs_dir, processed_cycle_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile the selected NHANES components and variables.")
    parser.add_argument("--cycle", default=DEFAULT_CYCLE, help="NHANES cycle label to profile.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidate_rows, variable_profile_rows = collect_cycle_artifacts(args.cycle)

    processed_dir = processed_cycle_dir(args.cycle)
    processed_dir.mkdir(parents=True, exist_ok=True)

    variable_profile_path = processed_dir / "nhanes_selected_variable_catalog.csv"
    variable_profile_df = pd.DataFrame(variable_profile_rows).sort_values(
        by=["source_component", "source_file", "variable_name"]
    )
    variable_profile_df.to_csv(variable_profile_path, index=False)

    candidate_df = pd.DataFrame(candidate_rows)
    counts_summary = (
        candidate_df.assign(
            patient_like_candidate=lambda df: df["likely_fhir_resource"].eq("Patient"),
            observation_like_candidate=lambda df: df["likely_fhir_resource"].eq("Observation"),
        )
        .groupby(["source_component", "source_file"], dropna=False)
        .agg(
            participants_with_data=("participant_id_if_available", lambda series: series.replace("", pd.NA).dropna().nunique()),
            candidate_rows=("candidate_id", "count"),
            patient_like_candidates=("patient_like_candidate", "sum"),
            observation_like_candidates=("observation_like_candidate", "sum"),
            json_ready_candidates=("json_ready", "sum"),
            needs_linked_context_candidates=("needs_linked_context", "sum"),
            good_for_pairing_candidates=("good_for_pairing", "sum"),
        )
        .reset_index()
    )

    selected_variable_counts = (
        variable_profile_df.groupby(["source_component", "source_file"], dropna=False)["variable_name"]
        .nunique()
        .rename("selected_variables")
        .reset_index()
    )

    counts_summary = counts_summary.merge(
        selected_variable_counts,
        on=["source_component", "source_file"],
        how="left",
    )
    counts_summary.insert(0, "cycle", args.cycle)

    output_path = outputs_dir() / "component_counts_summary.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts_summary.sort_values(by=["source_component", "source_file"]).to_csv(output_path, index=False)

    print(f"wrote {variable_profile_path}")
    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()

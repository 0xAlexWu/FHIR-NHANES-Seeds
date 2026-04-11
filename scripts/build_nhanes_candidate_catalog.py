#!/usr/bin/env python3
from __future__ import annotations

import argparse

import pandas as pd

from nhanes_common import DEFAULT_CYCLE, collect_cycle_artifacts, outputs_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the NHANES candidate seed catalog.")
    parser.add_argument("--cycle", default=DEFAULT_CYCLE, help="NHANES cycle label to process.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidate_rows, _ = collect_cycle_artifacts(args.cycle)

    candidate_df = pd.DataFrame(candidate_rows).sort_values(
        by=["likely_fhir_resource", "source_component", "source_file", "candidate_id"]
    )
    output_path = outputs_dir() / "candidate_seed_catalog.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_df.to_csv(output_path, index=False)
    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()

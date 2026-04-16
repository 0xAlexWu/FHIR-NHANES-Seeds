#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from nhanes_common import outputs_dir

BATCH_SIZE = 10
PAIR_INPUT_CSV = "nhanes_pilot15_pair_candidates.csv"
PAIR_INPUT_JSONL = "nhanes_pilot15_pair_candidates.jsonl"
PROMPT_DIR_NAME = "reviewer_batch_prompts"

REVIEWER_HEADER = """You are acting as an external reviewer in a clinical-data-to-FHIR pairing evaluation workflow.

You will review multiple candidate paired samples.
Apply the same scoring rubric independently to each item.
Do not compare items with each other.
Judge each pair only on its own merits.

For each item, return:
- pair_id
- faithfulness
- unsupported_fact
- omission
- naturalness
- context_leakage
- short_rationale
- flag_type

Scoring rubric:
- faithfulness: 1 = faithful, 0 = not faithful
- unsupported_fact: 1 = yes, 0 = no
- omission: 1 = yes, 0 = no
- naturalness: 1 to 5
- context_leakage: 1 = yes, 0 = no

Allowed flag_type values:
- none
- possible_hallucination
- possible_omission
- awkward_input
- context_leakage
- style_uncertainty
- other

Review principles:
1. Only judge alignment between the shown input text and the shown target FHIR JSON.
2. Do not assume facts from linked resources unless explicitly present in the shown target JSON.
3. Do not reward unsupported extra detail.
4. Be conservative about unsupported facts.
5. Be conservative about omission of core information.
6. If the target is sparse, do not punish the input for not containing unavailable details.

Return only a JSON array.
Do not include markdown.
Do not include any text before or after the JSON array.
"""


def pair_csv_path() -> Path:
    path = outputs_dir() / PAIR_INPUT_CSV
    if not path.exists():
        raise FileNotFoundError(f"Missing pair candidate CSV: {path}")
    return path


def load_pairs() -> pd.DataFrame:
    pairs = pd.read_csv(pair_csv_path(), low_memory=False)
    if pairs["pair_id"].duplicated().any():
        duplicated = pairs.loc[pairs["pair_id"].duplicated(), "pair_id"].tolist()
        raise ValueError(f"Duplicate pair_id values found: {duplicated[:5]}")
    return pairs.sort_values(by=["pair_id"]).reset_index(drop=True)


def parse_target_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return json.loads(value)


def render_item(row: pd.Series, item_number: int) -> str:
    target_json = json.dumps(parse_target_json(row["target_fhir_json"]), indent=2, ensure_ascii=True)
    return "\n".join(
        [
            f"ITEM {item_number}",
            f"pair_id: {row['pair_id']}",
            f"resource_type: {row['resource_type']}",
            f"input_style: {row['input_style']}",
            "input_text:",
            str(row["input_text"]),
            "target_fhir_json:",
            target_json,
        ]
    )


def build_prompt_text(batch: pd.DataFrame) -> str:
    items = [render_item(row, index) for index, (_, row) in enumerate(batch.iterrows(), start=1)]
    return REVIEWER_HEADER + "\n\n" + "\n\n\n".join(items) + "\n"


def unusually_long_items(pairs: pd.DataFrame) -> list[tuple[str, int]]:
    lengths = pairs["input_text"].str.len() + pairs["target_fhir_json"].str.len()
    threshold = max(800, int(lengths.mean() + 2 * lengths.std(ddof=0)))
    flagged = pairs.loc[lengths >= threshold, ["pair_id"]].copy()
    flagged["combined_length"] = lengths[lengths >= threshold].astype(int).values
    return list(flagged.sort_values(by="combined_length", ascending=False).itertuples(index=False, name=None))


def main() -> None:
    outputs = outputs_dir()
    outputs.mkdir(parents=True, exist_ok=True)
    prompt_dir = outputs / PROMPT_DIR_NAME
    prompt_dir.mkdir(parents=True, exist_ok=True)

    pairs = load_pairs()
    if len(pairs) != 30:
        raise ValueError(f"Expected exactly 30 NHANES pairs, found {len(pairs)}")

    batches: list[pd.DataFrame] = [
        pairs.iloc[start : start + BATCH_SIZE].copy()
        for start in range(0, len(pairs), BATCH_SIZE)
    ]

    index_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    packaged_pair_ids: list[str] = []

    for batch_number, batch in enumerate(batches, start=1):
        batch_id = f"review_batch_{batch_number:03d}"
        file_name = f"{batch_id}.txt"
        prompt_path = prompt_dir / file_name
        prompt_path.write_text(build_prompt_text(batch), encoding="utf-8")

        pair_ids = batch["pair_id"].tolist()
        packaged_pair_ids.extend(pair_ids)
        index_rows.append(
            {
                "batch_id": batch_id,
                "file_name": file_name,
                "start_pair_id": pair_ids[0],
                "end_pair_id": pair_ids[-1],
                "item_count": len(pair_ids),
            }
        )
        manifest_rows.append(
            {
                "batch_id": batch_id,
                "file_name": file_name,
                "item_count": len(pair_ids),
                "pair_ids": pair_ids,
            }
        )

    if len(packaged_pair_ids) != len(set(packaged_pair_ids)):
        raise ValueError("At least one pair_id was packaged more than once.")
    if set(packaged_pair_ids) != set(pairs["pair_id"]):
        raise ValueError("Packaged pair_ids do not match the source pair list.")

    index_path = outputs / "reviewer_batch_index.csv"
    manifest_path = outputs / "reviewer_batch_manifest.jsonl"
    summary_path = outputs / "reviewer_batching_summary.md"

    pd.DataFrame(index_rows).to_csv(index_path, index=False)
    with manifest_path.open("w", encoding="utf-8") as handle:
        for row in manifest_rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    long_items = unusually_long_items(pairs)
    full_batches = sum(1 for batch in batches if len(batch) == BATCH_SIZE)
    has_partial = any(len(batch) < BATCH_SIZE for batch in batches)
    summary_lines = [
        "# Reviewer Batching Summary",
        "",
        f"- Total number of NHANES pairs packaged: {len(pairs)}",
        f"- Total number of batches created: {len(batches)}",
        f"- Full 10-item batches created: {full_batches}",
        f"- Final partial batch present: {'yes' if has_partial else 'no'}",
        "",
        "## Unusually long items",
        "",
    ]
    if long_items:
        for pair_id, combined_length in long_items:
            summary_lines.append(f"- {pair_id} (combined_length={combined_length})")
    else:
        summary_lines.append("- None detected by the batching heuristic.")
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print(f"wrote {prompt_dir / 'review_batch_001.txt'}")
    print(f"wrote {prompt_dir / 'review_batch_002.txt'}")
    print(f"wrote {prompt_dir / 'review_batch_003.txt'}")
    print(f"wrote {index_path}")
    print(f"wrote {manifest_path}")
    print(f"wrote {summary_path}")


if __name__ == "__main__":
    main()

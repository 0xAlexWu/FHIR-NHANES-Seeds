# FHIR-nhanes-seeds

NHANES-only curation pipeline for building Patient- and Observation-oriented seed candidates from public NHANES source files.

This repository is intentionally independent from any Synthea-derived or Official-derived workflows. It is scoped to:

- NHANES source profiling
- candidate extraction
- mapping preparation
- pilot-seed shortlist recommendation

It does not generate paired variants, final paired samples, or dataset splits in this stage.

## First-pass scope

- Primary source: NHANES public data files and documentation/codebooks
- Initial cycle: `2017-2018`
- Primary components:
  - Demographics
  - Examination
  - Laboratory
- First-pass resource focus:
  - `Patient`
  - `Observation`

`Condition` is intentionally out of scope for the first pass unless a later NHANES source slice turns out to map very cleanly.

## Selected NHANES files

The first reproducible pass keeps the footprint small and reviewable:

- `DEMO_J` - Demographic Variables and Sample Weights
- `BMX_J` - Body Measures
- `BPX_J` - Blood Pressure
- `GHB_J` - Glycohemoglobin
- `TCHOL_J` - Total Cholesterol
- `BIOPRO_J` - Standard Biochemistry Profile

The scripts are cycle-configurable so additional NHANES cycles and files can be added later without changing the repo purpose.

## Repository layout

```text
/
├── README.md
├── requirements.txt
├── scripts/
│   ├── fetch_nhanes_data.py
│   ├── profile_nhanes_components.py
│   ├── build_nhanes_candidate_catalog.py
│   ├── recommend_nhanes_pilot.py
│   └── nhanes_common.py
├── data/
│   ├── raw/
│   └── processed/
└── outputs/
    └── nhanes/
        ├── component_counts_summary.csv
        ├── observation_profile_summary.csv
        ├── candidate_seed_catalog.csv
        ├── candidate_seed_catalog.csv.gz
        └── nhanes_source_summary.md
```

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/fetch_nhanes_data.py
python3 scripts/profile_nhanes_components.py
python3 scripts/build_nhanes_candidate_catalog.py
python3 scripts/recommend_nhanes_pilot.py
```

## Output intent

- `component_counts_summary.csv`
  - file-level and resource-level counts for the first-pass NHANES candidate pool
- `candidate_seed_catalog.csv`
  - one row per potential seed candidate
- `candidate_seed_catalog.csv.gz`
  - GitHub-friendly compressed copy of the full catalog for versioned sharing
- `observation_profile_summary.csv`
  - overall Observation-oriented pool quality signals for pilot selection
- `nhanes_source_summary.md`
  - conservative recommendation for the first NHANES pilot subset

## Modeling notes

- Preserve semi-structured source character where it helps realism.
- Favor measurements and demographic slices that already look like forms, tables, or laboratory outputs.
- Be conservative about variables that depend on hidden context, reference-method substitutions, or heavy interpretation.
- Treat NHANES as a semi-structured realism source first, not as the sole backbone for final paired sample generation.

## GitHub note

The full candidate catalog is large enough to exceed GitHub's normal single-file size limit when stored as plain CSV. The scripts still generate `outputs/nhanes/candidate_seed_catalog.csv` locally, and the repository keeps a compressed `outputs/nhanes/candidate_seed_catalog.csv.gz` copy for GitHub publication.

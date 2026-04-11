# NHANES Source Summary

## Cycle used

- `2017-2018`

## Components used

- Demographics (`DEMO_J`)
- Examination (`BMX_J`, `BPX_J`)
- Laboratory (`GHB_J`, `TCHOL_J`, `BIOPRO_J`)

## Candidate pool

- Patient-like candidates: 9254
- Observation-like candidates: 205987
- Observation-like candidates marked pairing-friendly: 186743

## First-pilot suitability

The current NHANES-derived pool looks suitable for a first pilot. The Observation-oriented slice is materially cleaner than the Patient-oriented slice because the examination and laboratory files carry explicit measurement values, frequent units, and lower ambiguity than public-use demographic attributes.

## Backbone vs realism assessment

NHANES looks more useful here as a semi-structured realism source than as a backbone source. The strongest candidates preserve table-like and measurement-like character, while many public-use fields still need cautious interpretation or source-specific context before they become polished final pairs.

## Recommended pilot size

- Recommended first pilot shortlist size: 12
- Recommended mix: 9 Observation-focused candidates and 3 Patient-focused candidates

## Rationale

- Keep the first pilot small enough for quick review and mapping cleanup.
- Overweight Observation candidates because units and numeric values are more consistently pairing-friendly.
- Keep a small Patient subset so demographic bundling can be tested without forcing full patient reconstruction too early.
- Continue treating Condition as out of scope until a clearly low-ambiguity NHANES mapping emerges.

## Top pairing-friendly Observation measure types

- Diastolic: Blood pres [n=19959]; Systolic: Blood pres [n=19959]; Weight [n=8580]; Standing Height [n=8016]; Body Mass Index (kg/m^2) [n=8005]

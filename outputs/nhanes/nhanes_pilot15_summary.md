# NHANES Pilot 15 Summary

## Final counts by resource type

- Patient: 5
- Observation: 10
- Condition: 0

## Strict preferred criteria coverage

- Selected seeds meeting the strict preferred criteria: 15 / 15

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

- BMXWT: Weight, BMXHT: Standing Height, BMXBMI: Body Mass Index (kg/m^2), BPXSY1: Systolic: Blood pres, BPXDI1: Diastolic: Blood pres, LBXGH: Glycohemoglobin, LBXTC: Total Cholesterol, LBXSCR: Creatinine, refrigerated serum, LBXSAL: Albumin, refrigerated serum, LBXSCA: Total Calcium

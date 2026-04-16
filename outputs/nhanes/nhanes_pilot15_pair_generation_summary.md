# NHANES Pilot 15 Pair Generation Summary

## Totals

- Total number of seeds processed: 15
- Total number of pairs generated: 30

## Variants per resource type

- Patient: 10
- Observation: 20

## Variants per input style

- concise_clinical: 15
- semi_structured: 15

## Seeds that were difficult to express cleanly

- NHANES-P15-01, NHANES-P15-04, NHANES-P15-05, NHANES-P15-09, NHANES-P15-10, NHANES-P15-11, NHANES-P15-12, NHANES-P15-13, NHANES-P15-14, NHANES-P15-15

## Rows flagged for manual review

- 20 pairs were flagged for first-pass manual review.
- NHANES-P15-01-concise_clinical, NHANES-P15-01-semi_structured, NHANES-P15-04-concise_clinical, NHANES-P15-04-semi_structured, NHANES-P15-05-concise_clinical, NHANES-P15-05-semi_structured, NHANES-P15-09-concise_clinical, NHANES-P15-09-semi_structured, NHANES-P15-10-concise_clinical, NHANES-P15-10-semi_structured, NHANES-P15-11-concise_clinical, NHANES-P15-11-semi_structured ...

## Pairing assessment

NHANES looks stronger here as a semi-structured pairing source than as a free-text source. The generated inputs stay cleanest when they remain measurement-like or form-like, while more natural free-text phrasing would add avoidable risk of omission or unsupported detail.

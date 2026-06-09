# Evaluation Report

## Deterministic filters
- checks passed: 95/96
- noise precision/recall: 1.00 / 1.00
- job-candidate precision/recall: 1.00 / 1.00

## EXTRACTION (scored=30, skipped=0)
- is_job_application accuracy: 0.97 (P 0.96 / R 1.00)
- company match: 1.00
- role match: 1.00
- status accuracy: 0.96

### Status confusion (rows=expected, cols=predicted)
expected\predicted | Applied | In Review | Interview Scheduled | Rejected | Offer
Applied | 9 | 0 | 0 | 0 | 0
In Review | 0 | 2 | 0 | 0 | 0
Interview Scheduled | 0 | 1 | 4 | 0 | 0
Rejected | 0 | 0 | 0 | 6 | 0
Offer | 0 | 0 | 0 | 0 | 3

## OVERALL: PASS

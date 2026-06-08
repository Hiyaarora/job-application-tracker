# Evaluation Report

## Deterministic filters
- checks passed: 95/96
- noise precision/recall: 1.00 / 1.00
- job-candidate precision/recall: 1.00 / 1.00

## EXTRACTION (scored=22, skipped=8)
- is_job_application accuracy: 1.00 (P 1.00 / R 1.00)
- company match: 1.00
- role match: 0.94
- status accuracy: 1.00

### Status confusion (rows=expected, cols=predicted)
expected\predicted | Applied | In Review | Interview Scheduled | Rejected | Offer
Applied | 8 | 0 | 0 | 0 | 0
In Review | 0 | 1 | 0 | 0 | 0
Interview Scheduled | 0 | 0 | 3 | 0 | 0
Rejected | 0 | 0 | 0 | 4 | 0
Offer | 0 | 0 | 0 | 0 | 2

## OVERALL: PASS

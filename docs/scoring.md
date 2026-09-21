# Repo Health Score v1

Score v1 is frozen. The canonical implementation is
`repo_health.scoring.v1.ScoreEngineV1`; no API, analyzer or persistence module
implements a competing formula.

The six category weights are Documentation 0.15, Activity 0.15, Issues 0.15,
CI/CD 0.15, Security 0.20 and Code Health 0.20. Numeric categories are
normalized over the available denominator. Weighted quality is coverage ×
confidence. A full score requires at least five numeric categories and K ≥ 0.75;
a provisional score requires at least four and K ≥ 0.50. Otherwise the result
is `INSUFFICIENT_DATA` and has no overall score.

Security caps remain frozen: confirmed high findings cap at 60, while confirmed
critical or secret findings cap at 40. Missing data is represented as a
limitation, not a numeric zero. Every result retains category scores, status,
coverage, confidence, evidence references, applied caps and policy digests.

Calibration-v2 policy functions live in `repo_health.scoring.calibration_v2` and
are tested by golden fixtures. Changing weights, K, caps or calibration policy
requires a new version and explicit parity evidence.

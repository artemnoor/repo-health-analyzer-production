# Repo Health Score research lab

This directory contains deterministic, non-production experiments for the six-category
Repo Health Score methodology. It intentionally does not import or modify the production
Score Engine.

## Reproduce

From the repository root:

```text
python spikes/scoring/formula_lab.py
python spikes/scoring/formula_lab.py --json
```

The experiment uses only the Python standard library. The input scenarios are embedded
in `formula_lab.py` so the result is reproducible without credentials, network access,
or a runtime dependency.

## What it checks

- weighted arithmetic, weighted geometric, and hybrid aggregation;
- fixed top-level weights: Security and Code Health 20% each, other categories 15% each;
- explicit missing-data states and evidence-quality coverage `K`;
- Security critical-finding cap;
- score/provisional/insufficient-data presentation state;
- required counterfactual scenarios;
- monotonicity and missing-data invariants;
- sensitivity to category weights, Security cap, and presentation thresholds.

The real-fixture snapshot used in the methodology is deliberately recorded as a sanitized
observation in `docs/repo-health-score-methodology.md`; no token, comment text, or source
code is part of this experiment.

The real public-cohort calibration artifacts and release decision are documented in
[`docs/repo-health-score-calibration.md`](../../docs/repo-health-score-calibration.md)
and stored under `spikes/scoring/calibration/`.

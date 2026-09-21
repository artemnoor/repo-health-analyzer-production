# Calibration summary

Calibration-v2 behavior retained in the standalone package:

- Documentation: completeness, instructions, Vale quality and readability.
- Activity: unique commits, recency, meaningful ratio, authors and empty commits.
- Issues: SourceCraft responsiveness, resolution, backlog and maintenance with
  explicit partial-component handling.
- CI/CD: failure rate, streak and duration reliability components.
- Security: AppSec severity penalties and Score v1 caps.
- Code Health: SonarQube maintainability/debt/smells, complexity, duplication,
  TODO history, hotspots and Git structure.

The exact expected values and evidence semantics are executable in
`tests/golden/repo_health/test_analyzer_calibration_v2.py` and
`test_score_v1_target.py`.

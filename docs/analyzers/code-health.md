# Code Health analyzer

- ID: `repo-health.code-health`
- Input: normalized SonarQube, git-sizer, Git history and TODO/FIXME facts.
- Output: `CategoryResult` with maintainability/complexity/duplication,
  hotspot/churn and Git-structure evidence, coverage/confidence and limits.
- Policy: `code-health-v1` in `config/analyzers/code-health.yaml`; the legacy
  file-level RepoWise engine remains a compatibility implementation, not a
  competing repository score.
- External engines: SonarQube service/API and git-sizer through process
  boundaries; copied source trees are not required by the worker artifact.

Unavailable tools are visible as skipped/error capabilities. The analyzer
does not import another analyzer or score directly from raw tool output.

Checks: code-health fixture tests, native adapter tests and the frozen parity
suite.

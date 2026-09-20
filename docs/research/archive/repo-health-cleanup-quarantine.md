# Repo Health cleanup quarantine

Date: 2026-09-20

The Phase 7 cleanup moved only generated/local research material out of the
working tree. The operation is reversible: the original files remain under
`%TEMP%\repo-health-cleanup-quarantine-20260920` on the audit machine.

Moved groups:

- `$out/` — extracted SonarQube runtime, approximately 973 MB;
- ten `spikes/**/upstream/` source snapshots, approximately 1.2 GB;
- the downloaded git-sizer executable;
- the downloaded Vale archive and extracted Vale runtime.
- the pre-normalization `vendor/collectoss` copy, retained at
  `vendor-collectoss-before-pinned-20260921` while the pinned Git tree was
  re-materialized with UTF-8/LF content.

The working tree retains spike README/provenance files, scripts, calibration
reports and selected live evidence. The copied `vendor/` trees were not
deleted. License files from the moved upstream snapshots and the previous
CollectOSS copy remain in the quarantine until the legal owner confirms the
final archive/deletion policy.

The quarantine is not a production dependency and is not referenced by the
package or worker artifact. Restore is a manual operation from the listed
temporary directory if a research replay requires one of the snapshots.

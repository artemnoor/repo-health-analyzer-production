"""Frozen Code Health calibration-v2 policy metadata."""

import hashlib

POLICY_VERSION = "code-health-calibration-v2"
POLICY_DIGEST = hashlib.sha256(POLICY_VERSION.encode()).hexdigest()

__all__ = ["POLICY_DIGEST", "POLICY_VERSION"]

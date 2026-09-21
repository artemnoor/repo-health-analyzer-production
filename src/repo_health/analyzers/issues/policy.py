"""Frozen Issues partial-component policy metadata."""

import hashlib

POLICY_VERSION = "issues-sourcecraft-policy-v1"
POLICY_DIGEST = hashlib.sha256(POLICY_VERSION.encode()).hexdigest()

__all__ = ["POLICY_DIGEST", "POLICY_VERSION"]

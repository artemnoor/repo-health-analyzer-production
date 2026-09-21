"""Frozen SourceCraft AppSec policy and Score v1 cap metadata."""

import hashlib

POLICY_VERSION = "security-appsec-v1"
POLICY_DIGEST = hashlib.sha256(POLICY_VERSION.encode()).hexdigest()
SECURITY_CAPS = {"confirmed_high": 60.0, "confirmed_critical": 40.0, "confirmed_secret": 40.0}

__all__ = ["POLICY_DIGEST", "POLICY_VERSION", "SECURITY_CAPS"]

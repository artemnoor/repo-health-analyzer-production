"""Small shared infrastructure ports for the backend-only product."""

from .git import CheckoutPort, ExplicitCheckout, GitCollector, GitRunner
from .process import ProcessOutput, ProcessRequest, SubprocessProcess
from .redaction import digest, redact_mapping, redact_text, relative_path

__all__ = [
    "CheckoutPort",
    "ExplicitCheckout",
    "GitCollector",
    "GitRunner",
    "ProcessOutput",
    "ProcessRequest",
    "SubprocessProcess",
    "digest",
    "redact_mapping",
    "redact_text",
    "relative_path",
]

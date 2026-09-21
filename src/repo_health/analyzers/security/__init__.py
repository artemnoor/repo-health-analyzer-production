"""Security analyzer boundary; factory is composed explicitly."""

from .factory import ANALYZER_ID, SecurityAnalyzer, analyze, bind_security_analyzer

__all__ = ["ANALYZER_ID", "SecurityAnalyzer", "analyze", "bind_security_analyzer"]

"""Activity analyzer boundary; factory is composed explicitly."""

from .factory import ANALYZER_ID, ActivityAnalyzer, analyze, bind_activity_analyzer

__all__ = ["ANALYZER_ID", "ActivityAnalyzer", "analyze", "bind_activity_analyzer"]

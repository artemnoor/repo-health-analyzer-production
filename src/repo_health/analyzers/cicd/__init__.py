"""CI/CD analyzer boundary; factory is composed explicitly."""

from .factory import ANALYZER_ID, CicdAnalyzer, analyze, bind_cicd_analyzer

__all__ = ["ANALYZER_ID", "CicdAnalyzer", "analyze", "bind_cicd_analyzer"]

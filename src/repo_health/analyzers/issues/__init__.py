"""Issues analyzer boundary; factory is composed explicitly."""

from .factory import ANALYZER_ID, IssuesAnalyzer, analyze, bind_issues_analyzer

__all__ = ["ANALYZER_ID", "IssuesAnalyzer", "analyze", "bind_issues_analyzer"]

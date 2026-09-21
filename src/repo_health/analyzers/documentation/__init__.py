"""Documentation analyzer boundary; factory is composed explicitly."""

from .factory import ANALYZER_ID, DocumentationAnalyzer, analyze, bind_documentation_analyzer

__all__ = ["ANALYZER_ID", "DocumentationAnalyzer", "analyze", "bind_documentation_analyzer"]

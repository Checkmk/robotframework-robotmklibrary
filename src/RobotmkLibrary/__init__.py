"""Keyword library for Robot Framework suites run by Robotmk.

``Library RobotmkLibrary`` imports the keywords, which live in
``RobotmkLibrary.keyword_monitoring``.
"""

from RobotmkLibrary.keyword_monitoring import monitor_subsequent_keyword_runtime

__all__ = ["monitor_subsequent_keyword_runtime"]

"""Keyword library for Robot Framework suites run by Robotmk.

``Library RobotmkLibrary`` imports the keywords, which live in
``RobotmkLibrary.runtime``.
"""

from RobotmkLibrary.runtime import monitor_subsequent_keyword_runtime

__all__ = ["monitor_subsequent_keyword_runtime"]

"""Keyword library for Robot Framework suites run by Robotmk.

``Library RobotmkLibrary`` imports the keywords, which live in
``RobotmkLibrary.runtime``. The trace listener is
``RobotmkLibrary.instrumentation.listener.RobotmkListener``.
"""

from importlib.metadata import version

from RobotmkLibrary.runtime import monitor_subsequent_keyword_runtime

__version__ = version("robotframework-robotmklibrary")
__all__ = ["monitor_subsequent_keyword_runtime"]

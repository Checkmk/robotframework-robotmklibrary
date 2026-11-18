"""Types for the objects Robot Framework passes to the listener hooks.

Robot Framework calls ``start_suite(data, result)``, ``end_keyword(data, result)``,
``log_message(message)`` and so on with its own ``robot.result`` and
``robot.model`` objects, but ships no type information for them. The protocols
below declare the attributes the listener reads from those objects, suite and
test results, keyword and body item results, log messages, so that the hooks
are type-checked without importing ``robot``.
"""

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class Status(StrEnum):
    """The result status of a Robot Framework suite, test, keyword or body item."""

    PASS = "PASS"  # noqa: S105 Flagged by ruffs credentials heuristics
    FAIL = "FAIL"
    SKIP = "SKIP"
    NOT_RUN = "NOT RUN"


class StatusResult(Protocol):
    """The parts of a Robot Framework result object every span needs."""

    @property
    def status(self) -> str: ...
    @property
    def message(self) -> str: ...
    @property
    def start_time(self) -> datetime | None: ...
    @property
    def end_time(self) -> datetime | None: ...


class Result(StatusResult, Protocol):
    @property
    def name(self) -> str: ...


class TestResult(Result, Protocol):
    @property
    def full_name(self) -> str: ...


class KeywordResult(TestResult, Protocol):
    @property
    def type(self) -> str: ...
    @property
    def args(self) -> Sequence[object]: ...


class BodyItemResult(StatusResult, Protocol):
    @property
    def type(self) -> str: ...


class Message(Protocol):
    @property
    def message(self) -> str: ...
    @property
    def level(self) -> str: ...
    @property
    def html(self) -> bool: ...
    @property
    def timestamp(self) -> datetime | None: ...

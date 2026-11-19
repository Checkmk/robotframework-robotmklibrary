"""Isolation shared by the unit and integration tests."""

from collections.abc import Iterator

import pytest
from opentelemetry.test.globals_test import reset_logging_globals, reset_trace_globals


@pytest.fixture(autouse=True)
def _reset_opentelemetry_globals() -> Iterator[None]:
    # The listener registers its providers as process globals, which the SDK accepts once.
    yield
    reset_trace_globals()
    reset_logging_globals()

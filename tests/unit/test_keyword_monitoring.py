"""The keyword monitoring keyword called directly, without Robot Framework."""

import logging

import pytest

from RobotmkLibrary.keyword_monitoring import monitor_subsequent_keyword_runtime


@pytest.mark.parametrize(
    ("discover_as", "message"),
    [
        pytest.param(
            None,
            "The subsequent keyword will be discovered in Checkmk using its own name",
            id="own name",
        ),
        pytest.param(
            "Login",
            'The subsequent keyword will be discovered in Checkmk as: "Login"',
            id="given name",
        ),
    ],
)
def test_the_keyword_logs_the_checkmk_marker(
    caplog: pytest.LogCaptureFixture, discover_as: str | None, message: str
) -> None:
    """The keyword logs the marker Checkmk matches to discover the next keyword.

    The keyword is called with and without discover_as while the logger is
    captured. Outcome: one INFO record with the marker text, naming the given
    name when there is one.
    """
    caplog.set_level(logging.INFO, logger="RobotmkLibrary.keyword_monitoring")

    monitor_subsequent_keyword_runtime(discover_as=discover_as)

    assert caplog.records[0].levelname == "INFO"
    assert caplog.records[0].getMessage() == message

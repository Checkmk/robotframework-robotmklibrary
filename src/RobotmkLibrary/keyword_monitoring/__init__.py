"""Keywords for the runtime monitoring of the Checkmk test services."""

import logging

logger = logging.getLogger(__name__)


def monitor_subsequent_keyword_runtime(
    *,
    discover_as: str | None = None,
) -> None:
    """Log the marker that makes Checkmk discover the runtime of the next keyword."""
    logger.info(
        "The subsequent keyword will be discovered in Checkmk using its own name"
        if discover_as is None
        else f'The subsequent keyword will be discovered in Checkmk as: "{discover_as}"',
    )


__all__ = ["monitor_subsequent_keyword_runtime"]

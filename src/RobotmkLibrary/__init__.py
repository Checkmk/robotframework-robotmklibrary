from __future__ import annotations

import logging


def monitor_subsequent_keyword_runtime(
    *,
    discover_as: str | None = None,
) -> None:
    logging.info(
        "The subsequent keyword will be discovered in Checkmk using its own name"
        if discover_as is None
        else f'The subsequent keyword will be discovered in Checkmk as: "{discover_as}"',
    )

# pylint: disable=invalid-name, missing-module-docstring
import logging
from typing import Optional


def monitor_subsequent_keyword_runtime(  # pylint: disable=missing-function-docstring
    *,
    discover_as: Optional[str] = None,
) -> None:
    logging.info(
        "The subsequent keyword will be discovered in Checkmk using its own name"
        if discover_as is None
        else f'The subsequent keyword will be discovered in Checkmk as: "{discover_as}"'
    )

# pylint: disable=invalid-name, missing-module-docstring
import logging


def monitor_subsequent_keyword_runtime(  # pylint: disable=missing-function-docstring
    *,
    discover_as: str,
) -> None:
    logging.info(discover_as)

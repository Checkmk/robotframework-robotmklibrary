A keyword library for Robot Framework intended to be used in combination with Robotmk.

## Keywords

```robotframework
*** Settings ***
Library    RobotmkLibrary
```

| Keyword | Effect |
| --- | --- |
| `Monitor Subsequent Keyword Runtime    discover_as=` | logs the marker that makes Checkmk discover the runtime of the next keyword, under its own name or the given one |

### Development

```sh
uv sync
uv run ruff format --diff
uv run ruff check
uv run mypy src
uv run pytest
```

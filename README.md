A keyword library for Robot Framework intended to be used in combination with Robotmk.

## Keywords

```robotframework
*** Settings ***
Library    RobotmkLibrary
```

| Keyword | Effect |
| --- | --- |
| `Monitor Subsequent Keyword Runtime    discover_as=` | logs the marker that makes Checkmk discover the runtime of the next keyword, under its own name or the given one |

## Trace listener

`RobotmkLibrary.instrumentation.listener.RobotmkListener` exports a robot run as one OpenTelemetry
trace: the root span is the top level suite, child suites, tests and keywords nest
below it, and every log message becomes a log record of the innermost open span.
The export goes over OTLP/HTTP to the collector of a Checkmk site, which stores the
data in its synthetic monitoring database.

### Usage

```sh
pip install robotframework-robotmklibrary
export OTEL_EXPORTER_OTLP_ENDPOINT=https://site.example.com:4318
export CHECKMK_RESOURCE_ATTRIBUTES=cmk.application=otel_demo,cmk.suite=otel_demo_http,cmk.variant=,cmk.machine_id=426f61d315ae408796589657a55d53a1,cmk.plan_run_id=run-1,cmk.attempt=1
robot --listener RobotmkLibrary.instrumentation.listener.RobotmkListener suite.robot
```

In an RCC environment, add the package to the `pip:` section of `conda.yaml`.
The Robotmk scheduler sets the environment variables and the listener option for
every attempt of a plan.

### Listener arguments

| Argument | Fallback | Meaning |
| --- | --- | --- |
| `endpoint` | `OTEL_EXPORTER_OTLP_ENDPOINT` | base URL of the collector; `/v1/traces` and `/v1/logs` are appended |
| `headers` | `OTEL_EXPORTER_OTLP_HEADERS` | HTTP headers sent with every export request, as comma separated `key=value` pairs, e.g. `Authorization=Basic ...` for a receiver with basic auth |
| `certificate` | `OTEL_EXPORTER_OTLP_CERTIFICATE` | CA bundle for the server certificate |
| `timeout` | `OTEL_EXPORTER_OTLP_TIMEOUT`, 10 seconds | export timeout in seconds |
| `export_control_structures` | `false` | spans for `FOR`, `WHILE`, `IF`, `TRY` and `VAR` |
| `export_keyword_arguments` | `true` | `rf.keyword.args` on keyword spans |
| `max_log_length` | `500` | log bodies are cut at this length |
| `max_image_size` | 2 MiB | an embedded screenshot larger than this (base64 bytes) is dropped |
| `max_image_size_total` | 8 MiB | embedded screenshots beyond this total per run are dropped |

Robot Framework splits listener arguments at `:`, so use `;` as the separator
whenever a value contains a colon:

```sh
robot --listener "RobotmkLibrary.instrumentation.listener.RobotmkListener;endpoint=https://site.example.com:4318;timeout=5" suite.robot
```

### Development

```sh
uv sync
uv run ruff format --diff
uv run ruff check
uv run mypy src tests
uv run pytest
```

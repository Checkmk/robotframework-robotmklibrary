"""Robot Framework listener that exports a run as OpenTelemetry traces and logs.

Each robot run spans a new trace. The top level suite spans the root span,
child suites are nested spans below the root span. Log messages are exported as
OTLP logs.

Logs and traces get exported over OTLP/HTTP, configured through the listener
arguments or the standard ``OTEL_EXPORTER_OTLP_*`` envrionment variables:

    - ``OTEL_RESOURCE_ATTRIBUTES``: Additional resource attributes.
    ``CHECKMK_RESOURCE_ATTRIBUTES`` takes precendence.
    - ``OTEL_EXPORTER_OTLP_ENDPOINT``: Base URL of the collector.
    - ``OTEL_EXPORTER_OTLP_HEADERS``: Comma separated ``key=value`` pairs.
    - ``OTEL_EXPORTER_OTLP_CERTIFICATE``: CA bundle.
    - ``OTEL_EXPORTER_OTLP_TIMEOUT``: Export timeout in seconds.
    - ``OTEL_EXPORTER_OTLP_COMPRESSION``: ``gzip`` or none.

Handling of the traces identify if done through environment variables.
``CHECKMK_RESOURCE_ATTRIBUTES`` has all needed ``cmk.*`` resource attributes
set by the Robotmk scheduler. ``service.name`` is set to ``robotmk``. Those
attributes are merged with ``OTEL_RESOURCE_ATTRIBUTES``.
``CHECKMK_RESOURCE_ATTRIBUTES`` takes presendence over ``OTEL_RESOURCE_ATTRIBUTES``.

The listener registers its providers as the process globals and makes every
span it opens the current span of the OpenTelemetry context, so any other
instrumentation in the environment nests its spans below the running keyword.

Usage::

    robot --listener RobotmkLibrary.instrumentation.listener.RobotmkListener suite.robot
    robot --listener "RobotmkLibrary.instrumentation.listener.RobotmkListener;endpoint=https://site:4318;timeout=5" suite.robot

"""

import os
import re
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import Token
from datetime import datetime
from typing import Final, NamedTuple, assert_never

from opentelemetry import context, trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.util.types import AttributeValue

from RobotmkLibrary import __version__

from ._exceptions import (
    GlobalLoggerProviderAlreadySetError,
    GlobalTracerProviderAlreadySetError,
)
from ._logs import (
    BatchLogRecordProcessor,
    LoggerProvider,
    LogRecordExporter,
    OTLPLogExporter,
    SeverityNumber,
    get_logger_provider,
    set_logger_provider,
)
from ._protocols import (
    BodyItemResult,
    KeywordResult,
    Message,
    Result,
    Status,
    StatusResult,
    TestResult,
)

_SCOPE: Final = "RobotmkLibrary"
_MEBIBYTE: Final = 1024 * 1024
_EMBEDDED_IMAGE: Final = re.compile(
    r'<img\b[^>]*\bsrc="data:(?P<media_type>image/[\w.+-]+);base64,(?P<payload>[^"]*)"[^>]*>'
)


class _EmbeddedImage(NamedTuple):
    media_type: str
    payload: str


class _OpenSpan(NamedTuple):
    span: trace.Span
    token: Token[Context]


_SEVERITIES: Final[Mapping[str, SeverityNumber]] = {
    "TRACE": SeverityNumber.TRACE,
    "DEBUG": SeverityNumber.DEBUG,
    "INFO": SeverityNumber.INFO,
    "WARN": SeverityNumber.WARN,
    "ERROR": SeverityNumber.ERROR,
    "FAIL": SeverityNumber.ERROR,
    "SKIP": SeverityNumber.INFO,
}


def _datetime_to_nanoseconds(moment: datetime | None) -> int | None:
    if moment is None:
        return None
    return int(moment.timestamp()) * 1_000_000_000 + moment.microsecond * 1_000


def _parse_key_value_pairs(pairs: str | None) -> dict[str, str]:
    """Split ``key=value,key2=value2``. An empty value stays an empty string."""
    if not pairs:
        return {}
    return {
        key.strip(): value.strip()
        for key, _separator, value in (item.partition("=") for item in pairs.split(","))
    }


class RobotmkListener:
    """Listener (API v3) exporting the run as one trace with correlated log records.

    Robot Framework passes the arguments given with ``--listener`` and converts
    them to the annotated types. An exporter argument left out falls back to the
    matching ``OTEL_EXPORTER_OTLP_*`` variable and then to the SDK default.
    """

    # Used by the Robotframework listener library to determine the API version.
    ROBOT_LISTENER_API_VERSION: Final = 3

    def __init__(  # noqa: PLR0913
        self,
        *,
        endpoint: str | None = None,
        headers: str | None = None,
        certificate: str | None = None,
        timeout: float | None = None,
        export_control_structures: bool = False,
        export_keyword_arguments: bool = True,
        max_log_length: int = 500,
        max_image_size: int = 2 * _MEBIBYTE,
        max_image_size_total: int = 8 * _MEBIBYTE,
        span_exporter: SpanExporter | None = None,
        log_exporter: LogRecordExporter | None = None,
    ) -> None:
        """Create the OTel exporters and providers and register the providers as the globals.

        - ``endpoint``: base URL of the collector; ``/v1/traces`` and ``/v1/logs`` are appended.
        - ``headers``: HTTP headers sent with every export request, as comma separated
          ``key=value`` pairs, e.g. ``Authorization=Basic ...`` for a receiver with basic auth.
        - ``certificate``: CA bundle to verify the collector's certificate.
        - ``timeout``: export timeout in seconds.
        - ``export_control_structures``: spans for FOR, WHILE, IF, TRY and VAR.
        - ``export_keyword_arguments``: ``rf.keyword.args`` on keyword spans.
        - ``max_log_length``: log bodies are cut at this length.
        - ``max_image_size``: base64 bytes above which an embedded screenshot is dropped.
        - ``max_image_size_total``: base64 bytes of all screenshots of a run above which the rest is dropped.
        - ``span_exporter``, ``log_exporter``: seam to replace the OTLP exporters in tests.
        """
        parsed_headers = _parse_key_value_pairs(headers) or None
        self._span_exporter: SpanExporter = span_exporter or OTLPSpanExporter(
            endpoint=None if endpoint is None else f"{endpoint.rstrip('/')}/v1/traces",
            certificate_file=certificate,
            headers=parsed_headers,
            timeout=timeout,
        )
        self._log_exporter: LogRecordExporter = log_exporter or OTLPLogExporter(
            endpoint=None if endpoint is None else f"{endpoint.rstrip('/')}/v1/logs",
            certificate_file=certificate,
            headers=parsed_headers,
            timeout=timeout,
        )
        self._export_control_structures = export_control_structures
        self._export_keyword_arguments = export_keyword_arguments
        self._max_log_length = max_log_length
        self._max_image_size = max_image_size
        self._max_image_size_total = max_image_size_total
        self._image_total = 0
        self._span_stack: list[_OpenSpan | None] = []
        self._start_providers()

    def start_suite(self, _suite: object, result: Result) -> None:
        """Open the suite span."""
        with self._placeholder_on_failure():
            self._start_span(
                result.name, {"rf.type": "suite", "rf.suite.name": result.name}, result
            )

    def end_suite(self, _suite: object, result: Result) -> None:
        """Close the suite span with its status."""
        self._end_span(result)

    def start_test(self, _test: object, result: TestResult) -> None:
        """Open the test span, named after the test, with the long name as attribute."""
        with self._placeholder_on_failure():
            self._start_span(
                result.name,
                {
                    "rf.type": "test",
                    "rf.test.name": result.name,
                    "rf.test.full_name": result.full_name,
                },
                result,
            )

    def end_test(self, _test: object, result: TestResult) -> None:
        """Close the test span with its status and message."""
        self._end_span(result)

    def start_keyword(self, _keyword: object, result: KeywordResult) -> None:
        """Open the keyword span, named after the full keyword name."""
        with self._placeholder_on_failure():
            attributes: dict[str, AttributeValue] = {
                "rf.type": "keyword",
                "rf.keyword.name": result.full_name,
                "rf.keyword.type": result.type,
            }
            if self._export_keyword_arguments:
                # Robot Framework declares the arguments as strings, but a library
                # calling BuiltIn().run_keyword() with objects hands them through.
                # Wrapping it into str() for safety. Using four spaces as a separator
                # since this is following Robotframework conventions.
                attributes["rf.keyword.args"] = "    ".join(
                    str(argument) for argument in result.args
                )
            self._start_span(result.full_name, attributes, result)

    def end_keyword(self, _keyword: object, result: KeywordResult) -> None:
        """Close the keyword span with its status and message."""
        self._end_span(result)

    def start_body_item(self, _body_item: object, result: BodyItemResult) -> None:
        """Open a span for a control structure, or skip it while keeping the nesting."""
        if not self._export_control_structures:
            self._span_stack.append(None)
            return
        with self._placeholder_on_failure():
            self._start_span(
                result.type,
                {"rf.type": "control", "rf.control.type": result.type},
                result,
            )

    def end_body_item(self, _body_item: object, result: BodyItemResult) -> None:
        """Close the control structure span."""
        self._end_span(result)

    def log_message(self, message: Message) -> None:
        """Emit the message as a log record of the innermost open span.

        Every screenshot embedded into an HTML message becomes its own image
        record.
        """
        span = self._current_span()
        if span is None:
            return
        if message.html:
            images = [
                _EmbeddedImage(match["media_type"], match["payload"])
                for match in _EMBEDDED_IMAGE.finditer(message.message)
            ]
            if self._emit_screenshot_records(images, message, span):
                return
        self._emit_log_record(
            message,
            span,
            message.message[: self._max_log_length],
            {
                "rf.log.level": message.level,
                "rf.log.html": "true" if message.html else "false",
            },
        )

    def close(self) -> None:
        """Flush and shut down the providers."""
        self._tracer_provider.shutdown()
        self._logger_provider.shutdown()

    @contextmanager
    def _placeholder_on_failure(self) -> Generator[None]:
        """Push a placeholder if opening the span fails.

        Robot Framework calls the end hook even when the start hook raised, and
        the end hook pops one entry from the span stack. Without an entry for the
        failed start, it would pop the parent's entry and every later end hook
        would close the wrong span. The placeholder keeps the pairing: only the
        failed span is lost. The exception propagates so that Robot Framework
        reports it as a listener error.
        """
        try:
            yield
        except Exception:
            self._span_stack.append(None)
            raise

    def _start_providers(self) -> None:
        resource = Resource.create(
            {
                **_parse_key_value_pairs(os.environ.get("CHECKMK_RESOURCE_ATTRIBUTES")),
                "service.name": "robotmk",
            }
        )
        self._tracer_provider = TracerProvider(resource=resource)
        self._tracer_provider.add_span_processor(
            BatchSpanProcessor(self._span_exporter)
        )
        trace.set_tracer_provider(self._tracer_provider)
        if (
            tracer_provider := trace.get_tracer_provider()
        ) is not self._tracer_provider:
            raise GlobalTracerProviderAlreadySetError(tracer_provider)
        self._otel_tracer = self._tracer_provider.get_tracer(_SCOPE, __version__)
        self._logger_provider = LoggerProvider(resource=resource)
        self._logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(self._log_exporter)
        )
        set_logger_provider(self._logger_provider)
        if (logger_provider := get_logger_provider()) is not self._logger_provider:
            raise GlobalLoggerProviderAlreadySetError(logger_provider)
        self._otel_logger = self._logger_provider.get_logger(_SCOPE, __version__)

    def _start_span(
        self, name: str, attributes: Mapping[str, AttributeValue], result: StatusResult
    ) -> None:
        parent = self._current_span()
        span = self._otel_tracer.start_span(
            name,
            context=trace.set_span_in_context(parent) if parent is not None else None,
            attributes=attributes,
            start_time=_datetime_to_nanoseconds(result.start_time),
        )
        self._span_stack.append(
            _OpenSpan(span, context.attach(trace.set_span_in_context(span)))
        )

    def _end_span(self, result: StatusResult) -> None:
        if not self._span_stack or (open_span := self._span_stack.pop()) is None:
            return
        context.detach(open_span.token)
        span = open_span.span
        span.set_attribute("rf.status", result.status)
        match Status(result.status):
            case Status.PASS:
                span.set_status(trace.StatusCode.OK)
            case Status.FAIL:
                span.set_status(trace.StatusCode.ERROR, result.message)
            case Status.SKIP | Status.NOT_RUN:
                # Defaults to UNSET which indicates a successful run.
                # See: https://opentelemetry.io/docs/concepts/signals/traces/#span-status
                pass
            case other:
                assert_never(other)
        span.end(end_time=_datetime_to_nanoseconds(result.end_time))

    def _current_span(self) -> trace.Span | None:
        return next(
            (entry.span for entry in reversed(self._span_stack) if entry is not None),
            None,
        )

    def _emit_log_record(
        self,
        message: Message,
        span: trace.Span,
        body: str,
        attributes: Mapping[str, AttributeValue],
    ) -> None:
        timestamp = _datetime_to_nanoseconds(message.timestamp)
        self._otel_logger.emit(
            timestamp=timestamp,
            observed_timestamp=timestamp,
            context=trace.set_span_in_context(span),
            severity_text=message.level,
            severity_number=_SEVERITIES.get(message.level, SeverityNumber.UNSPECIFIED),
            body=body,
            attributes={"rf.log.level": message.level, **attributes},
        )

    def _emit_screenshot_records(
        self, images: list[_EmbeddedImage], message: Message, span: trace.Span
    ) -> bool:
        for image in images:
            size = len(image.payload)
            if size > self._max_image_size:
                body = f"Screenshot of {size} bytes dropped (max_image_size {self._max_image_size})"
                attributes: dict[str, AttributeValue] = {"rf.log.html": "false"}
            elif self._image_total + size > self._max_image_size_total:
                body = (
                    f"Screenshot of {size} bytes dropped "
                    f"(max_image_size_total {self._max_image_size_total})"
                )
                attributes = {"rf.log.html": "false"}
            else:
                self._image_total += size
                body = image.payload
                attributes = {"rf.log.html": "false", "rf.log.image": image.media_type}
            self._emit_log_record(message, span, body, attributes)
        return bool(images)

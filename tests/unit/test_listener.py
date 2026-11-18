"""The listener hooks called directly with stand-ins for the Robot Framework objects."""

from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypedDict, Unpack

import pytest
from opentelemetry import trace
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.util.types import AttributeValue

from RobotmkLibrary import __version__
from RobotmkLibrary.instrumentation._exceptions import (
    GlobalLoggerProviderAlreadySetError,
    GlobalTracerProviderAlreadySetError,
)
from RobotmkLibrary.instrumentation._logs import (
    LoggerProvider,
    SeverityNumber,
    set_logger_provider,
)
from RobotmkLibrary.instrumentation._protocols import StatusResult
from RobotmkLibrary.instrumentation.listener import RobotmkListener

PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
SELENIUM_SCREENSHOT = (
    '</td></tr><tr><td colspan="3"><img alt="screenshot" class="robot-seleniumlibrary-screenshot" '
    f'src="data:image/png;base64,{PNG}" width="800px">'
)
BROWSER_SCREENSHOT = (
    '</td></tr><tr><td colspan="3"><img alt="screenshot" class="robot-seleniumlibrary-screenshot" '
    f'style="max-width:900px;max-height:900px;" src="data:image/png;base64,{PNG}"/>'
)
FILE_SCREENSHOT = '</td></tr><tr><td colspan="3"><a href="shot.png"><img src="shot.png" width="800px"></a>'
PNG_LOG_ATTRIBUTES = {
    "rf.log.level": "INFO",
    "rf.log.html": "false",
    "rf.log.image": "image/png",
}


class ListenerOptions(TypedDict, total=False):
    """The tunable arguments of RobotmkListener, as the test helpers forward them."""

    export_control_structures: bool
    export_keyword_arguments: bool
    max_log_length: int
    max_image_size: int
    max_image_size_total: int


def _datetime_to_ns(datetime_: datetime) -> int:
    return int(datetime_.timestamp()) * 1_000_000_000 + datetime_.microsecond * 1_000


@dataclass
class Result:
    """Stand-in for the suite, test, keyword and body item results of Robot Framework."""

    name: str = "Demo"
    full_name: str = ""
    status: str = "PASS"
    message: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    type: str = "KEYWORD"
    args: Sequence[object] = ()

    def __post_init__(self) -> None:
        self.full_name = self.full_name or self.name


@dataclass
class Message:
    """Stand-in for a Robot Framework log message."""

    message: str
    level: str = "INFO"
    html: bool = False
    timestamp: datetime | None = None


class _InMemoryListener(RobotmkListener):
    """The listener with in-memory exporters, readable after close()."""

    def __init__(self, **options: Unpack[ListenerOptions]) -> None:
        self.spans = InMemorySpanExporter()
        self.logs = InMemoryLogRecordExporter()
        super().__init__(span_exporter=self.spans, log_exporter=self.logs, **options)


@contextmanager
def _make_listener(**options: Unpack[ListenerOptions]) -> Generator[_InMemoryListener]:
    listener = _InMemoryListener(**options)
    try:
        yield listener
    finally:
        listener.close()


@pytest.mark.parametrize(
    ("start", "end", "result", "name", "expected"),
    [
        pytest.param(
            RobotmkListener.start_suite,
            RobotmkListener.end_suite,
            Result(name="Demo", status="FAIL"),
            "Demo",
            {"rf.type": "suite", "rf.suite.name": "Demo", "rf.status": "FAIL"},
            id="suite",
        ),
        pytest.param(
            RobotmkListener.start_test,
            RobotmkListener.end_test,
            Result(name="Passes", full_name="Demo.Passes"),
            "Passes",
            {
                "rf.type": "test",
                "rf.test.name": "Passes",
                "rf.test.full_name": "Demo.Passes",
                "rf.status": "PASS",
            },
            id="test",
        ),
        pytest.param(
            RobotmkListener.start_keyword,
            RobotmkListener.end_keyword,
            Result(name="Log", full_name="BuiltIn.Log", type="SETUP"),
            "BuiltIn.Log",
            {
                "rf.type": "keyword",
                "rf.keyword.name": "BuiltIn.Log",
                "rf.keyword.type": "SETUP",
                "rf.keyword.args": "",
                "rf.status": "PASS",
            },
            id="keyword",
        ),
    ],
)
def test_each_result_becomes_one_span(
    start: Callable[[RobotmkListener, object, Result], None],
    end: Callable[[RobotmkListener, object, Result], None],
    result: Result,
    name: str,
    expected: dict[str, str],
) -> None:
    """Each result becomes one span.

    The start and end hooks are called with a result stand-in, without Robot
    Framework. Outcome: one span named after the result, carrying the rf.*
    attributes of its kind.
    """
    with _make_listener() as listener:
        start(listener, None, result)
        end(listener, None, result)

    (span,) = listener.spans.get_finished_spans()
    assert span.name == name
    assert dict(span.attributes or {}) == expected


def test_span_takes_times_from_robotframework_result() -> None:
    """The span starts and ends at the times of the result.

    A suite is started and ended with a result holding start and end times.
    Outcome: the span times are those times in nanoseconds since the epoch.
    """
    start_time = datetime(2026, 11, 17, 10, 0, 0, 250_000, tzinfo=UTC)
    end_time = datetime(2026, 11, 17, 10, 0, 1, 500_000, tzinfo=UTC)
    suite_result = Result(start_time=start_time, end_time=end_time)

    with _make_listener() as listener:
        listener.start_suite(None, suite_result)
        listener.end_suite(None, suite_result)

    (span,) = listener.spans.get_finished_spans()
    assert span.start_time == _datetime_to_ns(start_time)
    assert span.end_time == _datetime_to_ns(end_time)


@pytest.mark.parametrize(
    ("robotframework_status", "span_status_code", "description"),
    [
        pytest.param("PASS", "OK", None, id="pass"),
        pytest.param("FAIL", "ERROR", "500 != 200", id="fail"),
        pytest.param("SKIP", "UNSET", None, id="skip"),
        pytest.param("NOT RUN", "UNSET", None, id="not run"),
    ],
)
def test_the_robotframework_status_maps_to_the_span_status(
    robotframework_status: str, span_status_code: str, description: str | None
) -> None:
    """The Robot Framework status becomes the span status.

    A test with the given status is started and ended. Outcome: the span
    attribute rf.status holds the Robot status verbatim; the span status code
    is OK for PASS, ERROR with the failure message as description for FAIL,
    and UNSET for SKIP and NOT RUN.
    """
    test_result = Result(status=robotframework_status, message="500 != 200")

    with _make_listener() as listener:
        listener.start_test(None, test_result)
        listener.end_test(None, test_result)

    (span,) = listener.spans.get_finished_spans()
    assert (span.attributes or {})["rf.status"] == robotframework_status
    assert span.status.status_code.name == span_status_code
    assert span.status.description == description


def test_spans_nest_in_hook_order() -> None:
    """Nested hooks produce nested spans.

    A suite, a test and a keyword are started and ended in nesting order,
    followed by a second keyword in the same test. Outcome: the test span's
    parent is the suite span, the first keyword span's parent is the test
    span, and the second keyword's parent is the test span as well, not the
    ended first keyword.
    """
    suite_result = Result(name="Demo")
    test_result = Result(name="Passes")
    keyword_result = Result(name="Log")
    next_keyword_result = Result(name="Sleep")

    with _make_listener() as listener:
        listener.start_suite(None, suite_result)
        listener.start_test(None, test_result)
        listener.start_keyword(None, keyword_result)
        listener.end_keyword(None, keyword_result)
        listener.start_keyword(None, next_keyword_result)
        listener.end_keyword(None, next_keyword_result)
        listener.end_test(None, test_result)
        listener.end_suite(None, suite_result)

    spans_by_name = {span.name: span for span in listener.spans.get_finished_spans()}
    assert spans_by_name["Demo"].parent is None

    passes_parent = spans_by_name["Passes"].parent
    assert passes_parent is not None
    assert passes_parent.span_id == spans_by_name["Demo"].context.span_id

    log_parent = spans_by_name["Log"].parent
    assert log_parent is not None
    assert log_parent.span_id == spans_by_name["Passes"].context.span_id

    sleep_parent = spans_by_name["Sleep"].parent
    assert sleep_parent is not None
    assert sleep_parent.span_id == spans_by_name["Passes"].context.span_id


def test_the_running_span_is_the_current_span_of_the_process() -> None:
    """The span of the running item is the OpenTelemetry current span.

    A test and a keyword are started and ended while the global current span
    is read after each hook. Outcome: the current span is the keyword span
    while the keyword runs, the test span again after the keyword ended, and
    no span after the test ended.
    """
    test_result = Result(name="Test")
    keyword_result = Result(name="Log")

    with _make_listener() as listener:
        listener.start_test(None, test_result)
        listener.start_keyword(None, keyword_result)
        current_during_keyword = trace.get_current_span()
        listener.end_keyword(None, keyword_result)
        current_after_keyword = trace.get_current_span()
        listener.end_test(None, test_result)
        current_after_test = trace.get_current_span()

    spans_by_name = {span.name: span for span in listener.spans.get_finished_spans()}
    assert current_during_keyword.get_span_context() == spans_by_name["Log"].context
    assert current_after_keyword.get_span_context() == spans_by_name["Test"].context
    assert current_after_test is trace.INVALID_SPAN


def test_spans_and_records_carry_the_library_scope() -> None:
    """Spans and log records carry the library as instrumentation scope.

    A suite with one log message runs through the hooks. Outcome: span and
    record name the scope RobotmkLibrary with the package version.
    """
    suite_result = Result()

    with _make_listener() as listener:
        listener.start_suite(None, suite_result)
        listener.log_message(Message("hello"))
        listener.end_suite(None, suite_result)

    (span,) = listener.spans.get_finished_spans()
    (log,) = listener.logs.get_finished_logs()
    assert span.instrumentation_scope is not None
    assert span.instrumentation_scope.name == "RobotmkLibrary"
    assert span.instrumentation_scope.version == __version__

    assert log.instrumentation_scope is not None
    assert log.instrumentation_scope.name == "RobotmkLibrary"
    assert log.instrumentation_scope.version == __version__


def test_control_structures_are_skipped_by_default_and_keep_the_nesting() -> None:
    """Control structures get no span by default and do not break the nesting.

    A FOR body item between a test and a keyword runs through the hooks with the
    default options. Outcome: only the test and keyword spans exist, and the
    keyword span's parent is the test span.
    """
    test_result = Result(name="Test")
    loop_result = Result(type="FOR")
    keyword_result = Result(name="Log")

    with _make_listener() as listener:
        listener.start_test(None, test_result)
        listener.start_body_item(None, loop_result)
        listener.start_keyword(None, keyword_result)
        listener.end_keyword(None, keyword_result)
        listener.end_body_item(None, loop_result)
        listener.end_test(None, test_result)

    spans_by_name = {span.name: span for span in listener.spans.get_finished_spans()}
    assert set(spans_by_name) == {"Test", "Log"}
    assert "FOR" not in spans_by_name

    log_parent = spans_by_name["Log"].parent
    assert log_parent is not None
    assert log_parent.span_id == spans_by_name["Test"].context.span_id


def test_a_log_message_inside_a_skipped_control_structure_belongs_to_the_enclosing_span() -> (
    None
):
    """A message logged inside a control structure without a span goes to the span around it.

    A message is logged inside a FOR body item with the default options.
    Outcome: the record references the test span.
    """
    test_result = Result(name="Test")
    loop_result = Result(type="FOR")

    with _make_listener() as listener:
        listener.start_test(None, test_result)
        listener.start_body_item(None, loop_result)
        listener.log_message(Message("inside the loop"))
        listener.end_body_item(None, loop_result)
        listener.end_test(None, test_result)

    (span,) = listener.spans.get_finished_spans()
    (item,) = listener.logs.get_finished_logs()
    assert item.log_record.span_id == span.context.span_id


def test_control_structures_become_spans_on_request() -> None:
    """Control structures become spans with export_control_structures.

    A FOR body item between a test and a keyword runs through the hooks with
    export_control_structures on. Outcome: the FOR span exists between the test
    and the keyword span, carrying rf.type control and rf.control.type FOR.
    """
    test_result = Result(name="Test")
    loop_result = Result(type="FOR")
    keyword_result = Result(name="Log")

    with _make_listener(export_control_structures=True) as listener:
        listener.start_test(None, test_result)
        listener.start_body_item(None, loop_result)
        listener.start_keyword(None, keyword_result)
        listener.end_keyword(None, keyword_result)
        listener.end_body_item(None, loop_result)
        listener.end_test(None, test_result)

    spans_by_name = {span.name: span for span in listener.spans.get_finished_spans()}
    assert set(spans_by_name) == {"Test", "FOR", "Log"}
    assert "FOR" in spans_by_name
    assert dict(spans_by_name["FOR"].attributes or {}) == {
        "rf.type": "control",
        "rf.control.type": "FOR",
        "rf.status": "PASS",
    }

    for_parent = spans_by_name["FOR"].parent
    assert for_parent is not None
    assert for_parent.span_id == spans_by_name["Test"].context.span_id

    log_parent = spans_by_name["Log"].parent
    assert log_parent is not None
    assert log_parent.span_id == spans_by_name["FOR"].context.span_id


def test_a_failing_start_hook_keeps_the_stack_intact() -> None:
    """An exception in a start hook does not desynchronise the span stack.

    A listener subclass fails while opening the span of the keyword Greet; the
    hooks continue as Robot Framework would, with Greet's end hook and a
    following keyword. Outcome: the exception propagates, Greet has no span,
    and the following keyword's parent is still the test span.
    """

    class _FailingOnGreet(_InMemoryListener):
        def _start_span(
            self,
            name: str,
            attributes: Mapping[str, AttributeValue],
            result: StatusResult,
        ) -> None:
            if name == "Greet":
                raise ValueError(name)
            super()._start_span(name, attributes, result)

    test_result = Result(name="Test")
    greet_result = Result(name="Greet")
    log_result = Result(name="Log")
    listener = _FailingOnGreet()

    listener.start_test(None, test_result)
    with pytest.raises(ValueError, match="Greet"):
        # Robotframework catches and logs exceptions in listeners in production
        listener.start_keyword(None, greet_result)
    listener.end_keyword(None, greet_result)
    listener.start_keyword(None, log_result)
    listener.end_keyword(None, log_result)
    listener.end_test(None, test_result)

    listener.close()

    spans_by_name = {span.name: span for span in listener.spans.get_finished_spans()}
    assert set(spans_by_name) == {"Test", "Log"}

    log_parent = spans_by_name["Log"].parent
    assert log_parent is not None
    assert log_parent.span_id == spans_by_name["Test"].context.span_id


@pytest.mark.parametrize(
    ("args", "options", "expected"),
    [
        pytest.param(("500", "200"), {}, "500    200", id="strings"),
        pytest.param(({"a": 1}, 42, None), {}, "{'a': 1}    42    None", id="objects"),
        pytest.param((), {}, "", id="no arguments"),
        pytest.param(("x",), {"export_keyword_arguments": False}, None, id="off"),
    ],
)
def test_robotframework_keyword_arguments_are_exported_as_rf_keyword_args(
    args: Sequence[object], options: ListenerOptions, expected: str | None
) -> None:
    """Keyword arguments become the rf.keyword.args attribute.

    A keyword with the given arguments runs through the hooks. Outcome: strings
    and objects are joined by four spaces, no arguments give an empty attribute,
    and export_keyword_arguments=False leaves the attribute out.
    """
    keyword_result = Result(args=args)

    with _make_listener(**options) as listener:
        listener.start_keyword(None, keyword_result)
        listener.end_keyword(None, keyword_result)

    (span,) = listener.spans.get_finished_spans()
    assert (span.attributes or {}).get("rf.keyword.args") == expected


def test_a_log_message_becomes_a_record_of_the_open_span() -> None:
    """A log message becomes a log record of the span that is open.

    An HTML message is logged inside a keyword. Outcome: the record keeps the
    body, carries rf.log.level and rf.log.html and references the keyword span.
    """
    keyword_result = Result()

    with _make_listener() as listener:
        listener.start_keyword(None, keyword_result)
        listener.log_message(Message("<b>x</b>", html=True))
        listener.end_keyword(None, keyword_result)

    (span,) = listener.spans.get_finished_spans()
    (item,) = listener.logs.get_finished_logs()
    record = item.log_record
    record_attributes = record.attributes or {}

    assert record.body == "<b>x</b>"
    assert record_attributes["rf.log.level"] == "INFO"
    assert record_attributes["rf.log.html"] == "true"

    assert record.trace_id == span.context.trace_id
    assert record.span_id == span.context.span_id


def test_log_record_takes_timestamp_from_robotframework_message() -> None:
    """The log record is stamped with the time of the message.

    A message with a timestamp is logged inside a suite. Outcome: the record's
    timestamp is that time in nanoseconds since the epoch.
    """
    start_time = datetime(2026, 11, 17, 10, 0, 0, 250_000, tzinfo=UTC)
    with _make_listener() as listener:
        listener.start_suite(None, Result())
        listener.log_message(Message("x", timestamp=start_time))

    (item,) = listener.logs.get_finished_logs()
    assert item.log_record.timestamp == _datetime_to_ns(start_time)


@pytest.mark.parametrize(
    ("level", "severity"),
    [
        pytest.param("WARN", SeverityNumber.WARN, id="warn stays warn"),
        pytest.param("FAIL", SeverityNumber.ERROR, id="fail is error"),
        pytest.param("SKIP", SeverityNumber.INFO, id="skip is info"),
        pytest.param("HURZ", SeverityNumber.UNSPECIFIED, id="unknown is unspecified"),
    ],
)
def test_log_levels_map_to_severities_and_preserves_level_in_attribute(
    level: str, severity: SeverityNumber
) -> None:
    """The Robot Framework log level becomes the record severity.

    A message of the given level is logged inside a suite. Outcome: the
    severity text and rf.log.level are the level as given; the severity
    number is the OpenTelemetry level of the same name, ERROR for FAIL, INFO
    for SKIP and UNSPECIFIED for a level OpenTelemetry does not know.
    """
    with _make_listener() as listener:
        listener.start_suite(None, Result())
        listener.log_message(Message("x", level=level))

    (item,) = listener.logs.get_finished_logs()
    record = item.log_record
    assert record.severity_text == level
    assert record.severity_number == severity
    assert (record.attributes or {})["rf.log.level"] == level


def test_a_log_message_outside_any_span_is_dropped() -> None:
    """A log message with no open span is dropped.

    A message is logged before any start hook. Outcome: no log record.
    """
    with _make_listener() as listener:
        listener.log_message(Message("orphan"))

    assert not listener.logs.get_finished_logs()


def test_log_bodies_are_cut_at_max_log_length() -> None:
    """Log bodies are cut at max_log_length.

    "Hello world" is logged with max_log_length=5. Outcome: the record body is
    "Hello".
    """
    with _make_listener(max_log_length=5) as listener:
        listener.start_suite(None, Result())
        listener.log_message(Message("Hello world"))

    (item,) = listener.logs.get_finished_logs()
    assert item.log_record.body == "Hello"


@pytest.mark.parametrize(
    ("message", "records"),
    [
        pytest.param(SELENIUM_SCREENSHOT, [(PNG, PNG_LOG_ATTRIBUTES)], id="selenium"),
        pytest.param(BROWSER_SCREENSHOT, [(PNG, PNG_LOG_ATTRIBUTES)], id="browser"),
        pytest.param(
            FILE_SCREENSHOT,
            [(FILE_SCREENSHOT, {"rf.log.level": "INFO", "rf.log.html": "true"})],
            id="file based stays html",
        ),
        pytest.param(
            f'Before <img src="data:image/jpeg;base64,{PNG}"> after',
            [(PNG, {**PNG_LOG_ATTRIBUTES, "rf.log.image": "image/jpeg"})],
            id="text around the image is dropped",
        ),
        pytest.param(
            f'<img src="data:image/png;base64,{PNG}"><img src="data:image/png;base64,{PNG}">',
            [(PNG, PNG_LOG_ATTRIBUTES), (PNG, PNG_LOG_ATTRIBUTES)],
            id="two images",
        ),
    ],
)
def test_embedded_screenshots_become_image_records(
    message: str, records: list[tuple[str, dict[str, str]]]
) -> None:
    """Embedded screenshots become image log records.

    An HTML message as logged by SeleniumLibrary or Browser with EMBED, a
    file-based screenshot, text around an image, or two images is logged inside
    a keyword. Outcome: each data URI image becomes a record whose body is the
    base64 payload with rf.log.image set to its media type; surrounding text is
    dropped; a file-based screenshot stays an HTML record.
    """
    with _make_listener() as listener:
        listener.start_keyword(None, Result())
        listener.log_message(Message(message, html=True))

    assert [
        (item.log_record.body, dict(item.log_record.attributes or {}))
        for item in listener.logs.get_finished_logs()
    ] == records


def test_a_plain_text_message_is_never_an_image() -> None:
    """Image detection applies to HTML messages only.

    The SeleniumLibrary screenshot markup is logged with html=False. Outcome: an
    ordinary text record without rf.log.image.
    """
    with _make_listener() as listener:
        listener.start_keyword(None, Result())
        listener.log_message(Message(SELENIUM_SCREENSHOT, html=False))

    (item,) = listener.logs.get_finished_logs()
    assert "rf.log.image" not in (item.log_record.attributes or {})


def test_screenshot_payloads_are_not_cut_at_max_log_length() -> None:
    """max_log_length applies to text bodies only, not to screenshot payloads.

    A screenshot is logged with max_log_length below the payload size.
    Outcome: the record body is the whole base64 payload.
    """
    with _make_listener(max_log_length=5) as listener:
        listener.start_keyword(None, Result())
        listener.log_message(Message(SELENIUM_SCREENSHOT, html=True))

    (item,) = listener.logs.get_finished_logs()
    assert item.log_record.body == PNG


def test_a_screenshot_above_max_image_size_becomes_a_note() -> None:
    """A screenshot above max_image_size is replaced by a note.

    One screenshot is logged with a per-image cap below its payload size.
    Outcome: a text record naming the size and the cap instead of an image
    record.
    """
    with _make_listener(max_image_size=1) as listener:
        listener.start_keyword(None, Result())
        listener.log_message(Message(SELENIUM_SCREENSHOT, html=True))

    (item,) = listener.logs.get_finished_logs()
    assert item.log_record.body == (
        f"Screenshot of {len(PNG)} bytes dropped (max_image_size 1)"
    )


def test_screenshots_beyond_max_image_size_total_become_notes() -> None:
    """Screenshots are accepted until their sum crosses max_image_size_total.

    Two screenshots are logged with a per-run cap equal to one payload.
    Outcome: the first becomes an image record, the second a text record
    naming the size and the cap.
    """
    with _make_listener(max_image_size_total=len(PNG)) as listener:
        listener.start_keyword(None, Result())
        listener.log_message(Message(SELENIUM_SCREENSHOT, html=True))
        listener.log_message(Message(SELENIUM_SCREENSHOT, html=True))

    logs = listener.logs.get_finished_logs()
    assert [item.log_record.body for item in logs] == [
        PNG,
        f"Screenshot of {len(PNG)} bytes dropped (max_image_size_total {len(PNG)})",
    ]


def test_resource_attributes_come_from_the_checkmk_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHECKMK_RESOURCE_ATTRIBUTES becomes resource attributes.

    The variable holds comma separated key=value pairs, one with an empty
    value. Outcome: the span resource carries every pair as given.
    """
    monkeypatch.setenv(
        "CHECKMK_RESOURCE_ATTRIBUTES",
        "cmk.application=otel_demo,cmk.suite=otel_demo_http,cmk.variant=,cmk.attempt=1",
    )
    suite_result = Result()

    with _make_listener() as listener:
        listener.start_suite(None, suite_result)
        listener.end_suite(None, suite_result)

    expected = {
        "cmk.application": "otel_demo",
        "cmk.suite": "otel_demo_http",
        "cmk.variant": "",
        "cmk.attempt": "1",
    }

    (span,) = listener.spans.get_finished_spans()
    assert expected.items() <= span.resource.attributes.items()


def test_user_resource_attributes_are_merged_below_the_listener_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OTEL_RESOURCE_ATTRIBUTES is merged below the attributes the listener sets.

    Both variables are set, with OTEL_RESOURCE_ATTRIBUTES repeating
    cmk.application and service.name. Outcome: the user's own key is kept, the
    Checkmk value wins for cmk.application, and service.name stays robotmk.
    """
    monkeypatch.setenv("CHECKMK_RESOURCE_ATTRIBUTES", "cmk.application=otel_demo")
    monkeypatch.setenv(
        "OTEL_RESOURCE_ATTRIBUTES",
        "team=payments,cmk.application=spoofed,service.name=x",
    )
    suite_result = Result()

    with _make_listener() as listener:
        listener.start_suite(None, suite_result)
        listener.end_suite(None, suite_result)

    (span,) = listener.spans.get_finished_spans()
    assert span.resource.attributes["team"] == "payments"
    assert span.resource.attributes["cmk.application"] == "otel_demo"
    assert span.resource.attributes["service.name"] == "robotmk"


def test_a_foreign_global_tracer_provider_is_refused_loudly() -> None:
    """A global tracer provider set before the listener raises.

    Another tracer provider is registered globally, then the listener is
    constructed. Outcome: GlobalTracerProviderAlreadySetError naming the
    registered class.
    """
    trace.set_tracer_provider(TracerProvider())

    with (
        pytest.raises(
            GlobalTracerProviderAlreadySetError,
            match=r"tracer provider is already \S*\.TracerProvider;",
        ),
        _make_listener(),
    ):
        pass


def test_a_foreign_global_logger_provider_is_refused_loudly() -> None:
    """A global logger provider set before the listener raises.

    Another logger provider is registered globally, then the listener is
    constructed. Outcome: GlobalLoggerProviderAlreadySetError naming the
    registered class.
    """
    set_logger_provider(LoggerProvider())

    with (
        pytest.raises(
            GlobalLoggerProviderAlreadySetError,
            match=r"logger provider is already \S*\.LoggerProvider;",
        ),
        _make_listener(),
    ):
        pass


def test_close_without_a_run_is_harmless() -> None:
    """close() works without any hook having run.

    A fresh listener is closed. Outcome: no exception.
    """
    with _make_listener():
        pass

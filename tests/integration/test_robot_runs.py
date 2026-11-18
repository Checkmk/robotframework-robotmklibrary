"""The listener inside real Robot Framework runs."""

import io
from collections.abc import Sequence
from pathlib import Path

from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from robot import run as run_robot

from RobotmkLibrary.instrumentation.listener import RobotmkListener

SUITES = Path(__file__).parent / "suites"


class _InMemoryListener(RobotmkListener):
    """The listener with in-memory exporters, readable after the run."""

    def __init__(self, *, export_control_structures: bool = False) -> None:
        self.spans = InMemorySpanExporter()
        self.logs = InMemoryLogRecordExporter()
        super().__init__(
            span_exporter=self.spans,
            log_exporter=self.logs,
            export_control_structures=export_control_structures,
        )


def _run(listener: RobotmkListener, target: str, **robot_options: object) -> int:
    """Run ``target`` from ``SUITES`` under ``listener`` without output files."""
    return_code: int = run_robot(
        str(SUITES / target),
        listener=listener,
        output=None,
        log=None,
        report=None,
        stdout=io.StringIO(),
        **robot_options,
    )
    return return_code


def _span_tree(
    spans: Sequence[ReadableSpan],
) -> list[tuple[str, str | None, str, str, str]]:
    """(name, parent name, rf.type, rf.status, status code) per span, parents first."""
    names = {span.context.span_id: span.name for span in spans}
    return [
        (
            span.name,
            None if span.parent is None else names[span.parent.span_id],
            str((span.attributes or {})["rf.type"]),
            str((span.attributes or {})["rf.status"]),
            span.status.status_code.name,
        )
        for span in sorted(
            spans, key=lambda span: (span.start_time or 0, -(span.end_time or 0))
        )
    ]


def test_a_run_exports_the_suite_tree() -> None:
    """A robot run exports spans nested like the suite.

    demo.robot with a passing, a failing and a skipped test runs under the
    listener. Outcome: robot returns 1, and every suite, test and keyword is a
    span below its parent with the Robot status and the mapped span status.
    """
    listener = _InMemoryListener()

    assert _run(listener, "demo.robot") == 1

    assert _span_tree(listener.spans.get_finished_spans()) == [
        ("Demo", None, "suite", "FAIL", "ERROR"),
        ("Passes", "Demo", "test", "PASS", "OK"),
        ("Greet", "Passes", "keyword", "PASS", "OK"),
        ("BuiltIn.Log", "Greet", "keyword", "PASS", "OK"),
        ("BuiltIn.Log", "Greet", "keyword", "PASS", "OK"),
        ("BuiltIn.Log", "Passes", "keyword", "PASS", "OK"),
        ("Fails", "Demo", "test", "FAIL", "ERROR"),
        ("BuiltIn.Should Be Equal", "Fails", "keyword", "FAIL", "ERROR"),
        ("Skips", "Demo", "test", "SKIP", "UNSET"),
        ("BuiltIn.Skip", "Skips", "keyword", "SKIP", "UNSET"),
    ]


def test_setup_and_teardown_keywords_carry_their_type() -> None:
    """Setup and teardown keywords carry their type and nest where they ran.

    control.robot with a suite setup and a test teardown runs under the
    listener. Outcome: exactly one span each with rf.keyword.type SETUP and
    TEARDOWN, below the suite span and the test span respectively.
    """
    listener = _InMemoryListener()
    _run(listener, "control.robot")

    spans = listener.spans.get_finished_spans()
    spans_by_name = {span.name: span for span in spans}
    spans_by_keyword_type = {
        (span.attributes or {})["rf.keyword.type"]: span
        for span in spans
        if (span.attributes or {})["rf.type"] == "keyword"
        and (span.attributes or {})["rf.keyword.type"] != "KEYWORD"
    }
    assert set(spans_by_keyword_type) == {"SETUP", "TEARDOWN"}

    setup_parent = spans_by_keyword_type["SETUP"].parent
    assert setup_parent is not None
    assert setup_parent.span_id == spans_by_name["Control"].context.span_id

    teardown_parent = spans_by_keyword_type["TEARDOWN"].parent
    assert teardown_parent is not None
    assert (
        teardown_parent.span_id == spans_by_name["Control Structures"].context.span_id
    )


def test_log_records_belong_to_the_innermost_span() -> None:
    """Log messages become records of the keyword that logged them.

    demo.robot runs under the listener. Outcome: in log order, every message is
    a record of the BuiltIn keyword span that logged it, including the failure
    message and the skip reason.
    """
    listener = _InMemoryListener()
    _run(listener, "demo.robot")

    spans_by_id = {
        span.context.span_id: span for span in listener.spans.get_finished_spans()
    }
    assert [
        (spans_by_id[item.log_record.span_id].name, item.log_record.body)
        for item in listener.logs.get_finished_logs()
    ] == [
        ("BuiltIn.Log", "Hello world"),
        ("BuiltIn.Log", "<b>bold</b>"),
        ("BuiltIn.Log", "careful"),
        ("BuiltIn.Should Be Equal", "500 != 200"),
        ("BuiltIn.Skip", "not today"),
    ]


def test_control_structures_become_spans_on_request() -> None:
    """With export_control_structures, FOR and IF/ELSE become spans in the tree.

    control.robot runs with the option on. Outcome: FOR, ITERATION, IF/ELSE
    ROOT, IF and ELSE are control spans between the test and the keywords, and
    the ELSE branch that did not run carries NOT RUN with status UNSET.
    """
    listener = _InMemoryListener(export_control_structures=True)
    _run(listener, "control.robot")

    assert _span_tree(listener.spans.get_finished_spans()) == [
        ("Control", None, "suite", "PASS", "OK"),
        ("BuiltIn.Log", "Control", "keyword", "PASS", "OK"),
        ("Control Structures", "Control", "test", "PASS", "OK"),
        ("FOR", "Control Structures", "control", "PASS", "OK"),
        ("ITERATION", "FOR", "control", "PASS", "OK"),
        ("BuiltIn.Log", "ITERATION", "keyword", "PASS", "OK"),
        ("IF/ELSE ROOT", "Control Structures", "control", "PASS", "OK"),
        ("IF", "IF/ELSE ROOT", "control", "PASS", "OK"),
        ("BuiltIn.Log", "IF", "keyword", "PASS", "OK"),
        ("ELSE", "IF/ELSE ROOT", "control", "NOT RUN", "UNSET"),
        ("BuiltIn.Log", "ELSE", "keyword", "NOT RUN", "UNSET"),
        ("BuiltIn.Log", "Control Structures", "keyword", "PASS", "OK"),
    ]


def test_other_instrumentations_nest_below_the_running_keyword() -> None:
    """Spans from other instrumentations nest below the running keyword.

    library.robot calls a keyword that opens a span through the global tracer.
    Outcome: that span's parent is the keyword span and it keeps its own
    instrumentation scope.
    """
    listener = _InMemoryListener()
    _run(listener, "library.robot")

    spans_by_name = {span.name: span for span in listener.spans.get_finished_spans()}
    other = spans_by_name["http.request"]

    other_parent = other.parent
    assert other_parent is not None
    assert (
        other_parent.span_id
        == spans_by_name["current_span_library.Open A Span"].context.span_id
    )
    assert other.instrumentation_scope is not None
    assert other.instrumentation_scope.name == "other-instrumentation"


def test_an_unreachable_collector_does_not_fail_the_run() -> None:
    """An unreachable collector neither fails nor stalls the run.

    demo.robot runs with the real OTLP exporters pointed at a closed port and a
    one-second timeout. Outcome: robot returns 0.
    """
    return_code: int = run_robot(
        str(SUITES / "demo.robot"),
        test="Passes",
        listener="RobotmkLibrary.instrumentation.listener.RobotmkListener;endpoint=http://127.0.0.1:9;timeout=1",
        output=None,
        log=None,
        report=None,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert return_code == 0

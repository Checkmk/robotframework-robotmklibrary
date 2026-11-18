"""Robot Framework library whose keyword creates an OpenTelemetry span.

The keyword uses only the global tracer, like a library instrumented
independently of the listener would. The test asserts that this span
nests below the span of the running keyword.
"""

from opentelemetry import trace


def open_a_span() -> None:
    with trace.get_tracer("other-instrumentation").start_as_current_span(
        "http.request"
    ):
        pass

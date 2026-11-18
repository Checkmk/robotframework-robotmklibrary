*** Settings ***
Documentation    Calls a keyword that creates an OpenTelemetry span of its own.
...              The test asserts that the span nests below the keyword span.
Library    ${CURDIR}/current_span_library.py

*** Test Cases ***
Uses Another Instrumentation
    Open A Span

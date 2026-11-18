"""Errors raised by the trace listener."""


class GlobalTracerProviderAlreadySetError(RuntimeError):
    """Another instrumentation registered the global tracer provider first."""

    def __init__(self, registered: object) -> None:
        """Name the provider found in the global slot."""
        super().__init__(
            "The global OpenTelemetry tracer provider is already "
            f"{type(registered).__module__}.{type(registered).__name__}; "
            "another instrumentation configured OpenTelemetry before the listener"
        )


class GlobalLoggerProviderAlreadySetError(RuntimeError):
    """Another instrumentation registered the global logger provider first."""

    def __init__(self, registered: object) -> None:
        """Name the provider found in the global slot."""
        super().__init__(
            "The global OpenTelemetry logger provider is already "
            f"{type(registered).__module__}.{type(registered).__name__}; "
            "another instrumentation configured OpenTelemetry before the listener"
        )

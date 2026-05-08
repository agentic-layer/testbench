"""OpenTelemetry setup for testbench."""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk import trace as trace_sdk
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import SimpleSpanProcessor


def setup_otel() -> None:
    """Set up OpenTelemetry tracing for testbench."""

    # Set log level for urllib to WARNING to reduce noise
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Traces
    # Create resource with service name for proper trace identification
    resource = Resource.create({"service.name": "testbench.run"})
    tracer_provider = trace_sdk.TracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
    # Sets the global default tracer provider
    trace.set_tracer_provider(tracer_provider)

    # Instrument HTTPX clients (this also transfers the trace context automatically)
    HTTPXClientInstrumentor().instrument()

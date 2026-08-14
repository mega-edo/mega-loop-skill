"""Drop-in OpenTelemetry setup that emits the MEGA Loop trace contract.

Import and call `setup_tracing()` once, as early in your process as possible — before the app
creates any clients, because the auto-instrumentors patch libraries at import time.

    from instrument import setup_tracing
    setup_tracing(service_name="orders-agent")

What it configures:

* an OTLP exporter pointed at Langfuse, Phoenix or any OTel collector (chosen by env vars);
* the W3C `traceparent` propagator, so one request stays one trace across services;
* OpenInference auto-instrumentation for whichever LLM SDKs you have installed.

What it deliberately does not do: emit spans by hand. Use the helpers in `example_agent.py` or
the SDK's own API — hand-rolled spans are where propagation goes to die.

Install:

    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http \\
                openinference-instrumentation-openai openinference-instrumentation-anthropic
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

logger = logging.getLogger(__name__)

#: OpenInference instrumentors, tried in order. Missing ones are skipped without complaint —
#: instrumenting a library you do not use is not an error.
_INSTRUMENTORS = (
    ("openinference.instrumentation.openai", "OpenAIInstrumentor"),
    ("openinference.instrumentation.anthropic", "AnthropicInstrumentor"),
    ("openinference.instrumentation.langchain", "LangChainInstrumentor"),
    ("openinference.instrumentation.llama_index", "LlamaIndexInstrumentor"),
    ("openinference.instrumentation.bedrock", "BedrockInstrumentor"),
)


def _langfuse_headers() -> dict[str, str]:
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if not (public and secret):
        return {}
    token = base64.b64encode(f"{public}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _endpoint_and_headers() -> tuple[str, dict[str, str]]:
    """Resolve where to export. Explicit OTLP settings win; otherwise infer from the platform."""
    explicit = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if explicit:
        return explicit.rstrip("/") + "/v1/traces", {}

    langfuse_host = os.environ.get("LANGFUSE_HOST", "").strip()
    if langfuse_host:
        return langfuse_host.rstrip("/") + "/api/public/otel/v1/traces", _langfuse_headers()

    phoenix_host = os.environ.get("PHOENIX_HOST", "http://localhost:6006").strip()
    return phoenix_host.rstrip("/") + "/v1/traces", {}


def setup_tracing(
    *,
    service_name: str = "agent",
    service_version: str | None = None,
    resource_attributes: dict[str, Any] | None = None,
) -> trace.Tracer:
    """Configure the global tracer provider and return a tracer for your own spans.

    ``service_version`` is optional but worth setting: it is the standard OpenTelemetry field
    for "which build produced this trace", and it is what lets a downstream consumer tell a
    trace from before a fix apart from one after it. Pass a commit sha or a release tag.
    """
    attributes: dict[str, Any] = {"service.name": service_name}
    if service_version:
        attributes["service.version"] = service_version
    attributes.update(resource_attributes or {})

    endpoint, headers = _endpoint_and_headers()
    provider = TracerProvider(resource=Resource.create(attributes))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
    )
    trace.set_tracer_provider(provider)

    # Without this, cross-service calls start new traces instead of continuing this one.
    set_global_textmap(TraceContextTextMapPropagator())

    _install_instrumentors()
    logger.info("tracing configured: service=%s endpoint=%s", service_name, endpoint)
    return trace.get_tracer(service_name)


def _install_instrumentors() -> None:
    for module_name, class_name in _INSTRUMENTORS:
        try:
            module = __import__(module_name, fromlist=[class_name])
        except ImportError:
            continue  # library not installed — nothing to instrument
        getattr(module, class_name)().instrument()
        logger.info("instrumented %s", module_name.rsplit(".", 1)[-1])

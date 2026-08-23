"""Observability wiring. Exporters are optional so local development needs no accounts.

Structured JSON logs are always on: they are the one signal that must exist everywhere,
and every line carries the request id that the error envelope returns to the caller.
"""
import json
import logging
import sys
from typing import Any

from app.config import Settings, get_settings
from app.context import request_id_var

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    # Uvicorn installs its own handlers; force them through the JSON formatter.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def configure_sentry(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logging.getLogger(__name__).warning("SENTRY_DSN set but sentry-sdk is not installed")
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
    )
    return True


def configure_tracing(app: Any = None, settings: Settings | None = None) -> bool:
    """Install OTLP tracing when both an endpoint and the optional extra are present."""
    settings = settings or get_settings()
    if not settings.otel_exporter_otlp_endpoint:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logging.getLogger(__name__).warning(
            "OTEL endpoint set but the 'telemetry' extra is not installed"
        )
        return False

    resource = Resource.create(
        {"service.name": settings.service_name, "deployment.environment": settings.app_env}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)

    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready")
        except ImportError:
            logging.getLogger(__name__).warning("FastAPI OTel instrumentation is not installed")
    return True


def setup_telemetry(app: Any = None, settings: Settings | None = None) -> dict[str, bool]:
    settings = settings or get_settings()
    configure_logging(settings)
    return {
        "logging": True,
        "sentry": configure_sentry(settings),
        "tracing": configure_tracing(app, settings),
    }

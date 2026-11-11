//! Drop-in OpenTelemetry setup that emits the MEGA Loop trace contract from Rust.
//!
//! Copy this file into your crate and call [`setup_tracing`] once, first thing in `main`:
//!
//! ```ignore
//! let provider = instrument::setup_tracing("orders-agent", Some(env!("CARGO_PKG_VERSION")))?;
//! // ... serve requests ...
//! provider.shutdown()?; // flush before exit, or a short-lived process exports nothing
//! ```
//!
//! What it configures:
//!
//! * an OTLP/HTTP exporter pointed at Langfuse, Phoenix or any OTel collector (chosen by env vars,
//!   exactly as the Python and Node kits choose);
//! * a batch processor, which exports from its own thread — a blocking exporter called from a
//!   tokio worker would panic;
//! * the W3C `traceparent` propagator, so one request stays one trace across services.
//!
//! Rust has no OpenInference auto-instrumentation, so every LLM / TOOL / AGENT / RETRIEVER span is
//! yours to open. The helpers below set the kind at creation and keep the attribute names exact.
//!
//! Context does not follow work onto `tokio::spawn` or `spawn_blocking` by itself. Pass the
//! parent [`Context`] into the task, or wrap the future with `FutureExt::with_context`; a span
//! opened without its parent starts a trace of its own (`M2_tree_intact`).

use std::collections::HashMap;
use std::time::SystemTime;

use opentelemetry::propagation::TextMapPropagator;
use opentelemetry::trace::{Status, TraceContextExt, Tracer};
use opentelemetry::{Context, KeyValue, global};
use opentelemetry_otlp::{WithExportConfig, WithHttpConfig};
use opentelemetry_sdk::Resource;
use opentelemetry_sdk::propagation::TraceContextPropagator;
use opentelemetry_sdk::trace::SdkTracerProvider;
use serde_json::Value;

/// The instrumentation scope your spans are recorded under.
pub const TRACER: &str = "mega-loop-trace-kit";

/// Step text past this many characters is cut, with a marker saying how much went: 16k chars
/// stays under the validator's 50 kB per-attribute weight even at 3 bytes per char.
/// The root's `input.value` is never cut — it is what a fix verification replays.
pub const MAX_VALUE_CHARS: usize = 16_000;

/// Where to export, and with which headers. Explicit OTLP settings win; otherwise infer the
/// platform. With nothing set it is a local Phoenix on :6006.
pub fn endpoint_and_headers() -> (String, HashMap<String, String>) {
    let var = |k: &str| {
        std::env::var(k)
            .ok()
            .map(|v| v.trim().to_string())
            .filter(|v| !v.is_empty())
    };
    if let Some(explicit) = var("OTEL_EXPORTER_OTLP_ENDPOINT") {
        return (
            format!("{}/v1/traces", explicit.trim_end_matches('/')),
            HashMap::new(),
        );
    }
    // LANGFUSE_BASE_URL is the current name; LANGFUSE_HOST is what it was called before v4.
    if let Some(host) = var("LANGFUSE_BASE_URL").or_else(|| var("LANGFUSE_HOST")) {
        let mut headers = HashMap::new();
        if let (Some(public), Some(secret)) =
            (var("LANGFUSE_PUBLIC_KEY"), var("LANGFUSE_SECRET_KEY"))
        {
            let token = base64(format!("{public}:{secret}").as_bytes());
            headers.insert("Authorization".to_string(), format!("Basic {token}"));
        }
        return (
            format!("{}/api/public/otel/v1/traces", host.trim_end_matches('/')),
            headers,
        );
    }
    let phoenix = var("PHOENIX_HOST").unwrap_or_else(|| "http://localhost:6006".to_string());
    (
        format!("{}/v1/traces", phoenix.trim_end_matches('/')),
        HashMap::new(),
    )
}

/// Configures the global tracer provider. Keep the returned provider and shut it down on exit.
///
/// `service_version` is optional but worth setting: it is the standard OpenTelemetry field for
/// "which build produced this trace" — pass a commit sha or a release tag.
pub fn setup_tracing(
    service_name: &str,
    service_version: Option<&str>,
) -> Result<SdkTracerProvider, opentelemetry_otlp::ExporterBuildError> {
    let (endpoint, headers) = endpoint_and_headers();
    let exporter = opentelemetry_otlp::SpanExporter::builder()
        .with_http()
        .with_endpoint(endpoint)
        .with_headers(headers)
        .build()?;
    let mut resource = Resource::builder().with_service_name(service_name.to_string());
    if let Some(v) = service_version {
        resource = resource.with_attribute(KeyValue::new("service.version", v.to_string()));
    }
    let provider = SdkTracerProvider::builder()
        .with_batch_exporter(exporter)
        .with_resource(resource.build())
        .build();
    install(provider.clone());
    Ok(provider)
}

/// Makes `provider` the global one. Install exactly one: spans from a second provider dangle.
pub fn install(provider: SdkTracerProvider) {
    global::set_tracer_provider(provider);
    // Without this, cross-service calls start new traces instead of continuing this one.
    global::set_text_map_propagator(TraceContextPropagator::new());
}

/// Opens a span of OpenInference `kind` (CHAIN, AGENT, LLM, TOOL, RETRIEVER, …) under `parent`
/// and returns a context holding it. The kind is set at creation, so nothing can stamp over it.
pub fn start(name: &str, kind: &str, parent: &Context) -> Context {
    start_at(name, kind, parent, None)
}

/// [`start`] with an explicit start time, for a step you record after it ran (a replayed log).
pub fn start_at(name: &str, kind: &str, parent: &Context, at: Option<SystemTime>) -> Context {
    let tracer = global::tracer(TRACER);
    let mut builder = tracer
        .span_builder(name.to_string())
        .with_attributes([KeyValue::new("openinference.span.kind", kind.to_string())]);
    if let Some(t) = at {
        builder = builder.with_start_time(t);
    }
    let span = builder.start_with_context(&tracer, parent);
    parent.with_span(span)
}

pub fn set(cx: &Context, key: impl Into<String>, value: impl Into<opentelemetry::Value>) {
    cx.span().set_attribute(KeyValue::new(key.into(), value));
}

pub fn clip(text: &str) -> String {
    let n = text.chars().count();
    if n <= MAX_VALUE_CHARS {
        return text.to_string();
    }
    let head: String = text.chars().take(MAX_VALUE_CHARS).collect();
    format!("{head}…[{} more chars]", n - MAX_VALUE_CHARS)
}

/// The root's `input.value`, verbatim: it is the request MEGA Loop replays to verify a fix, so a
/// cut one would replay a different request. Store a reference instead if it is a whole file.
pub fn input(cx: &Context, value: &str) {
    set(cx, "input.value", value.to_string());
}

/// A step's `input.value`, clipped like its output: nothing replays a step's arguments, and a
/// large one would otherwise be stored whole on every run (`S4_payload_weight`).
pub fn step_input(cx: &Context, value: &str) {
    set(cx, "input.value", clip(value));
}

pub fn output(cx: &Context, value: &str) {
    set(cx, "output.value", clip(value));
}

/// A failed step says so in its status. An error returned as OK text is invisible to detection.
pub fn fail(cx: &Context, message: &str) {
    cx.span().set_status(Status::error(message.to_string()));
}

pub fn end(cx: &Context) {
    cx.span().end();
}

pub fn end_at(cx: &Context, at: SystemTime) {
    cx.span().end_with_timestamp(at);
}

/// Runs one tool call inside a TOOL span carrying its arguments, its result, and ERROR on failure.
pub fn tool<T: std::fmt::Display, E: std::fmt::Display>(
    parent: &Context,
    name: &str,
    args: &Value,
    call: impl FnOnce(&Context) -> Result<T, E>,
) -> Result<T, E> {
    let cx = start(name, "TOOL", parent);
    set(&cx, "tool.name", name.to_string());
    step_input(&cx, &args.to_string());
    let res = call(&cx);
    match &res {
        Ok(out) => output(&cx, &out.to_string()),
        Err(e) => {
            output(&cx, &e.to_string());
            fail(&cx, &e.to_string());
        }
    }
    end(&cx);
    res
}

/// One model call as the contract reads it.
#[derive(Default)]
pub struct LlmCall<'a> {
    pub model: &'a str,
    /// `(role, content)` — roles are system, user, assistant, tool or function.
    pub input_messages: &'a [(&'a str, &'a str)],
    pub output: &'a str,
    /// `(function name, arguments)` — arguments must be a JSON object.
    pub tool_calls: &'a [(&'a str, Value)],
    /// The `tools` argument exactly as the client passed it (`S5_declared_tools`).
    pub tools: &'a [Value],
    /// Leave `None` when the client does not report them: a recorded zero is itself a signal.
    pub prompt_tokens: Option<i64>,
    pub completion_tokens: Option<i64>,
}

/// Records `call` on an open LLM span.
pub fn record_llm(cx: &Context, call: &LlmCall) {
    set(cx, "llm.model_name", call.model.to_string());
    for (i, (role, content)) in call.input_messages.iter().enumerate() {
        set(
            cx,
            format!("llm.input_messages.{i}.message.role"),
            role.to_string(),
        );
        set(
            cx,
            format!("llm.input_messages.{i}.message.content"),
            clip(content),
        );
    }
    if let Some((_, last)) = call.input_messages.last() {
        step_input(cx, last);
    }
    for (i, tool) in call.tools.iter().enumerate() {
        set(
            cx,
            format!("llm.tools.{i}.tool.json_schema"),
            tool.to_string(),
        );
    }
    set(cx, "llm.output_messages.0.message.role", "assistant");
    set(
        cx,
        "llm.output_messages.0.message.content",
        clip(call.output),
    );
    for (j, (name, args)) in call.tool_calls.iter().enumerate() {
        let base = format!("llm.output_messages.0.message.tool_calls.{j}.tool_call.function");
        set(cx, format!("{base}.name"), name.to_string());
        set(cx, format!("{base}.arguments"), args.to_string());
    }
    output(cx, call.output);
    if let (Some(p), Some(c)) = (call.prompt_tokens, call.completion_tokens) {
        set(cx, "llm.token_count.prompt", p);
        set(cx, "llm.token_count.completion", c);
        set(cx, "llm.token_count.total", p + c);
    }
}

/// The headers to send on a call to another service, so its spans continue this trace.
/// The receiver extracts them with the same propagator and opens its spans under the result.
pub fn inject(cx: &Context) -> HashMap<String, String> {
    let mut headers = HashMap::new();
    TraceContextPropagator::new().inject_context(cx, &mut headers);
    headers
}

/// The receiving side of [`inject`].
pub fn extract(headers: &HashMap<String, String>) -> Context {
    TraceContextPropagator::new().extract(headers)
}

fn base64(bytes: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let n = chunk
            .iter()
            .enumerate()
            .fold(0u32, |acc, (i, b)| acc | (u32::from(*b) << (16 - 8 * i)));
        for i in 0..4 {
            out.push(if i <= chunk.len() {
                T[(n >> (18 - 6 * i) & 63) as usize] as char
            } else {
                '='
            });
        }
    }
    out
}

#[cfg(test)]
mod tests {
    #[test]
    fn base64_matches_rfc4648() {
        assert_eq!(super::base64(b"pk-lf-1:sk-lf-2"), "cGstbGYtMTpzay1sZi0y");
        assert_eq!(super::base64(b"a"), "YQ==");
        assert_eq!(super::base64(b"ab"), "YWI=");
    }
}

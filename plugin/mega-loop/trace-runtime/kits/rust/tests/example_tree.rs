//! The example request comes out as one trace of the documented shape, and is written in the
//! flat form `validate_traces.py --file` grades (`target/example-trace.json`).

use std::time::{SystemTime, UNIX_EPOCH};

use mega_loop_trace_kit::{example, instrument};
use opentelemetry::trace::{SpanId, Status};
use opentelemetry_sdk::trace::{InMemorySpanExporter, SdkTracerProvider, SpanData};
use serde_json::{Value, json};

fn attr(s: &SpanData, key: &str) -> Option<String> {
    s.attributes
        .iter()
        .find(|kv| kv.key.as_str() == key)
        .map(|kv| kv.value.as_str().to_string())
}

/// OTLP-style nanoseconds since the epoch; the validator reads numbers past 1e12 as nanos.
fn nanos(t: SystemTime) -> u64 {
    t.duration_since(UNIX_EPOCH).unwrap().as_nanos() as u64
}

fn flat(s: &SpanData) -> Value {
    let attributes: serde_json::Map<String, Value> = s
        .attributes
        .iter()
        .map(|kv| {
            let v = match &kv.value {
                opentelemetry::Value::I64(i) => json!(i),
                opentelemetry::Value::F64(f) => json!(f),
                opentelemetry::Value::Bool(b) => json!(b),
                other => json!(other.as_str()),
            };
            (kv.key.to_string(), v)
        })
        .collect();
    let (code, message) = match &s.status {
        Status::Error { description } => ("ERROR", description.to_string()),
        Status::Ok => ("OK", String::new()),
        Status::Unset => ("UNSET", String::new()),
    };
    json!({
        "span_id": s.span_context.span_id().to_string(),
        "trace_id": s.span_context.trace_id().to_string(),
        "parent_id": if s.parent_span_id == SpanId::INVALID { String::new() } else { s.parent_span_id.to_string() },
        "name": s.name,
        "span_kind": attr(s, "openinference.span.kind").unwrap_or_default(),
        "status_code": code,
        "status_message": message,
        "start_time": nanos(s.start_time),
        "end_time": nanos(s.end_time),
        "attributes": attributes,
    })
}

#[tokio::test(flavor = "multi_thread")]
async fn example_request_is_one_trace_of_the_documented_shape() {
    let exporter = InMemorySpanExporter::default();
    let provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter.clone())
        .build();
    instrument::install(provider.clone());

    let answer = example::handle_request("How many orders shipped late last week?").await;
    assert_eq!(answer.as_deref(), Ok("2 orders shipped late."));
    provider.force_flush().unwrap();
    let spans = exporter.get_finished_spans().unwrap();

    let by = |name: &str| {
        spans
            .iter()
            .find(|s| s.name == name)
            .unwrap_or_else(|| panic!("no {name} span"))
    };
    let root = by("POST /chat");
    assert_eq!(root.parent_span_id, SpanId::INVALID);
    assert!(
        attr(root, "input.value")
            .unwrap()
            .contains("orders shipped late")
    );
    for s in &spans {
        assert_eq!(
            s.span_context.trace_id(),
            root.span_context.trace_id(),
            "{} left the trace",
            s.name
        );
    }

    let expect = [
        ("plan", "LLM", "POST /chat"),
        ("query_orders", "TOOL", "POST /chat"),
        ("research_agent", "AGENT", "POST /chat"),
        ("search_docs", "RETRIEVER", "research_agent"),
        ("answer", "LLM", "POST /chat"),
        ("audit_log", "TOOL", "POST /chat"),
    ];
    for (name, kind, parent) in expect {
        let s = by(name);
        assert_eq!(
            attr(s, "openinference.span.kind").as_deref(),
            Some(kind),
            "{name}"
        );
        assert_eq!(
            s.parent_span_id,
            by(parent).span_context.span_id(),
            "{name} parent"
        );
        assert!(
            attr(s, "input.value").is_some() && attr(s, "output.value").is_some(),
            "{name} io"
        );
    }
    let plan = by("plan");
    assert!(
        attr(plan, "llm.tools.0.tool.json_schema")
            .unwrap()
            .contains("query_orders")
    );
    let args = attr(
        plan,
        "llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments",
    )
    .unwrap();
    assert!(serde_json::from_str::<Value>(&args).unwrap().is_object());

    let out = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("target/example-trace.json");
    std::fs::create_dir_all(out.parent().unwrap()).unwrap();
    std::fs::write(
        &out,
        serde_json::to_string_pretty(&spans.iter().map(flat).collect::<Vec<_>>()).unwrap(),
    )
    .unwrap();
}

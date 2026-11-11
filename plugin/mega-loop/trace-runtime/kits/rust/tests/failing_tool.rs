//! Its own test binary: it installs a global provider, which must not race the example's.

use mega_loop_trace_kit::instrument;
use opentelemetry::trace::Status;
use opentelemetry_sdk::trace::{InMemorySpanExporter, SdkTracerProvider};
use serde_json::json;

#[test]
fn a_failing_tool_is_an_error_span() {
    let exporter = InMemorySpanExporter::default();
    let provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter.clone())
        .build();
    instrument::install(provider.clone());
    let root = opentelemetry::Context::new();
    let res: Result<String, String> =
        instrument::tool(&root, "query_orders", &json!({"window": ""}), |_| {
            Err("window is required".into())
        });
    assert!(res.is_err());
    provider.force_flush().unwrap();
    let spans = exporter.get_finished_spans().unwrap();
    let s = spans
        .iter()
        .find(|s| s.name == "query_orders")
        .expect("tool span");
    assert!(matches!(s.status, Status::Error { .. }));
    let out = s
        .attributes
        .iter()
        .find(|kv| kv.key.as_str() == "output.value")
        .map(|kv| kv.value.as_str().to_string());
    assert_eq!(out.as_deref(), Some("window is required"));
}

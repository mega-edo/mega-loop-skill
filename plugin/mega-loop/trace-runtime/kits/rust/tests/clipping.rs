//! Its own test binary: it installs a global provider.

use mega_loop_trace_kit::instrument::{self, MAX_VALUE_CHARS};
use opentelemetry_sdk::trace::{InMemorySpanExporter, SdkTracerProvider};
use serde_json::json;

#[test]
fn root_input_is_verbatim_and_step_input_is_clipped() {
    let exporter = InMemorySpanExporter::default();
    let provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter.clone())
        .build();
    instrument::install(provider.clone());

    let big = "가".repeat(MAX_VALUE_CHARS + 500);
    let root = instrument::start("POST /chat", "CHAIN", &opentelemetry::Context::new());
    instrument::input(&root, &big);
    let _ = instrument::tool(&root, "ingest", &json!({ "doc": big }), |_| {
        Ok::<_, String>("ok".to_string())
    });
    instrument::end(&root);
    provider.force_flush().unwrap();

    let spans = exporter.get_finished_spans().unwrap();
    let input = |name: &str| {
        let s = spans.iter().find(|s| s.name == name).unwrap();
        s.attributes
            .iter()
            .find(|kv| kv.key.as_str() == "input.value")
            .map(|kv| kv.value.as_str().to_string())
            .unwrap()
    };
    assert_eq!(
        input("POST /chat"),
        big,
        "the root's request is replayed, so it is never cut"
    );
    let step = input("ingest");
    assert!(
        step.chars().count() < MAX_VALUE_CHARS + 50,
        "{}",
        step.chars().count()
    );
    assert!(step.contains("more chars]"));
}

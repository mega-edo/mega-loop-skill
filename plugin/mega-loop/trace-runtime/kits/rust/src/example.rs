//! A correctly-traced request: one root, nested steps, a sub-agent, a thread hop and a service hop.
//!
//! Run it and the platform should show **one** trace shaped like this:
//!
//! ```text
//! POST /chat                CHAIN   ← root, carries input.value
//! ├─ plan                   LLM     ← records the tools it offered
//! ├─ query_orders           TOOL    ← ran on a blocking thread, still a child
//! ├─ research_agent         AGENT   ← a sub-agent, not a new trace
//! │  └─ search_docs         RETRIEVER
//! ├─ answer                 LLM
//! └─ audit_log              TOOL    ← opened by the "downstream service" from traceparent
//! ```
//!
//! The fake model calls are not the point. The five numbered comments are the places a Rust
//! request normally fragments or goes quiet.

use std::collections::HashMap;

use opentelemetry::Context;
use serde_json::{Value, json};

use crate::instrument::{self, LlmCall};

pub const MODEL: &str = "claude-sonnet-5";

pub fn tools() -> Vec<Value> {
    vec![json!({
        "type": "function",
        "function": {
            "name": "query_orders",
            "description": "Orders in a time window, with whether each shipped late.",
            "parameters": {
                "type": "object",
                "properties": {"window": {"type": "string"}},
                "required": ["window"]
            }
        }
    })]
}

/// The request. Everything below it belongs to this one span.
pub async fn handle_request(question: &str) -> Result<String, String> {
    let root = instrument::start("POST /chat", "CHAIN", &Context::new());
    // (1) The root carries the user's question. Without it the trace cannot be replayed.
    instrument::input(&root, question);

    let result = run(&root, question).await;
    match &result {
        Ok(answer) => instrument::output(&root, answer),
        Err(e) => instrument::fail(&root, e),
    }
    instrument::end(&root);
    result
}

async fn run(root: &Context, question: &str) -> Result<String, String> {
    let window = plan_step(root, question);
    let rows = query_orders(root, window).await?;
    let context = research_agent(root, question);
    let answer = answer_step(root, question, &rows, &context);
    audit_service(&instrument::inject(root), &answer)?;
    Ok(answer)
}

fn plan_step(parent: &Context, question: &str) -> String {
    let cx = instrument::start("plan", "LLM", parent);
    let window = "last_week".to_string();
    // (2) Messages indexed from 0 with standard roles, the tools offered, and tool-call
    //     arguments as a JSON object.
    instrument::record_llm(
        &cx,
        &LlmCall {
            model: MODEL,
            input_messages: &[
                ("system", "You answer order questions."),
                ("user", question),
            ],
            output: "I will query the orders.",
            tool_calls: &[("query_orders", json!({"window": window}))],
            tools: &tools(),
            prompt_tokens: Some(412),
            completion_tokens: Some(38),
        },
    );
    instrument::end(&cx);
    window
}

async fn query_orders(parent: &Context, window: String) -> Result<String, String> {
    // (3) A thread hop. `spawn_blocking` (and `tokio::spawn`) start with an empty context, so the
    //     parent goes in by hand — open the span inside the task with it, never with
    //     `Context::current()` there.
    let parent = parent.clone();
    tokio::task::spawn_blocking(move || {
        instrument::tool(&parent, "query_orders", &json!({"window": window}), |_| {
            // (4) A failure returns Err, and the helper marks the span ERROR. Answering
            //     `{"error": …}` with an OK status is how a real bug becomes invisible.
            if window.is_empty() {
                return Err("window is required".to_string());
            }
            Ok(json!([{"id": 1, "late": true}, {"id": 2, "late": true}]).to_string())
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

/// A sub-agent is a span inside this trace, never a trace of its own.
fn research_agent(parent: &Context, question: &str) -> String {
    let cx = instrument::start("research_agent", "AGENT", parent);
    instrument::input(&cx, question);
    let docs = search_docs(&cx, question);
    instrument::output(&cx, &docs);
    instrument::end(&cx);
    docs
}

fn search_docs(parent: &Context, query: &str) -> String {
    let cx = instrument::start("search_docs", "RETRIEVER", parent);
    instrument::input(&cx, query);
    let doc = "Shipping SLA is 3 days.";
    instrument::set(&cx, "retrieval.documents.0.document.content", doc);
    instrument::set(&cx, "retrieval.documents.0.document.score", 0.91);
    instrument::output(&cx, doc);
    instrument::end(&cx);
    doc.to_string()
}

fn answer_step(parent: &Context, question: &str, rows: &str, context: &str) -> String {
    let cx = instrument::start("answer", "LLM", parent);
    let n = serde_json::from_str::<Vec<Value>>(rows).map_or(0, |r| r.len());
    let answer = format!("{n} orders shipped late.");
    let prompt = format!("{question}\nrows: {rows}\ncontext: {context}");
    instrument::record_llm(
        &cx,
        &LlmCall {
            model: MODEL,
            input_messages: &[("user", &prompt)],
            output: &answer,
            prompt_tokens: Some(486),
            completion_tokens: Some(21),
            ..Default::default()
        },
    );
    instrument::end(&cx);
    answer
}

/// (5) The service hop, receiving side. The caller sent `instrument::inject(root)` as HTTP
/// headers; this service extracts them and opens its spans under the result. Opened under a
/// fresh `Context::new()` instead, the same span would start a trace of its own.
pub fn audit_service(headers: &HashMap<String, String>, answer: &str) -> Result<(), String> {
    let parent = instrument::extract(headers);
    instrument::tool(&parent, "audit_log", &json!({"answer": answer}), |_| {
        Ok::<_, String>("logged".to_string())
    })
    .map(|_| ())
}

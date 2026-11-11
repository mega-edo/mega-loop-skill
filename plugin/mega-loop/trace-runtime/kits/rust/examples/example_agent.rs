//! `cargo run --example example_agent` — sends one trace to wherever `setup_tracing` points
//! (a local Phoenix on :6006 when nothing is set), then grade it:
//!
//!     uv run ../../scripts/validate_traces.py --platform phoenix --last 1

use mega_loop_trace_kit::{example, instrument};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let provider = instrument::setup_tracing("orders-agent", Some(env!("CARGO_PKG_VERSION")))?;
    let answer = example::handle_request("How many orders shipped late last week?").await;
    provider.shutdown()?; // flush before exit, or a short-lived process exports nothing
    println!("{}", answer?);
    Ok(())
}

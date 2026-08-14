# Span kinds, and what each one should carry

Set `openinference.span.kind` on every span. The kind decides which detectors look at it, so an
unrecognised kind is not a cosmetic problem — it is invisibility.

## The kinds

| Kind | Use it for |
|---|---|
| `CHAIN` | a request, a workflow, a business step. **The usual root.** |
| `AGENT` | an agent or sub-agent's turn |
| `LLM` | one model call |
| `TOOL` | one tool/function execution |
| `RETRIEVER` | a document/context lookup |
| `EMBEDDING` | an embedding call |
| `RERANKER` | a reranking call |
| `EVALUATOR` | a scoring/grading step |
| `GUARDRAIL` | a safety or policy check |

`SPAN` and `PROMPT` exist but read as *no kind was set*. They are not failures, but they are not
informative either.

## Required and expected keys

| Kind | Must have | Should have |
|---|---|---|
| root (`CHAIN`/`AGENT`) | `input.value` — the user's request | `output.value` — the final answer |
| `LLM` | `llm.model_name` | `llm.token_count.prompt` / `.completion` / `.total`, `llm.input_messages.*`, `llm.output_messages.*`, `llm.invocation_parameters` |
| `TOOL` | `input.value` (the arguments), `output.value` (the result) | the tool's name as the span name |
| `RETRIEVER` | `input.value` (the query) | `retrieval.documents.<i>.document.content` / `.score` |
| `EMBEDDING` | `llm.model_name` | `llm.token_count.prompt` |
| any errored span | status `ERROR` | `status_message` |

Token counts matter more than they look: they are how MEGA Loop attributes cost, and a zero
count is itself a detected signal.

## Message keys

```
llm.input_messages.<i>.message.role         system | user | assistant | tool | function
llm.input_messages.<i>.message.content
llm.output_messages.<i>.message.role
llm.output_messages.<i>.message.content
llm.output_messages.<i>.message.tool_calls.<j>.tool_call.function.name
llm.output_messages.<i>.message.tool_calls.<j>.tool_call.function.arguments   ← valid JSON
```

`arguments` must parse as a JSON object. Malformed tool arguments are one of the failure modes
MEGA Loop looks for, so emitting them as a bare string hides a real class of bug.

Indices are contiguous from 0, and `tool_calls.<j>` is counted **per message**.

## Declared tools

```
llm.tools.<i>.tool.json_schema    the schema you gave the model (function.name, function.parameters)
```

Worth emitting once per trace: it lets MEGA Loop tell "the model called a tool that does not
exist" apart from "the tool failed."

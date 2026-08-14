"""Lowering: a foreign dialect must reach the checks as OpenInference, and source data must win."""

from __future__ import annotations

from datetime import UTC, datetime

from tests.conftest import span

from trace_validator.span import flatten, lower_attributes, normalize, parse_time


def test_gen_ai_operation_name_sets_the_kind() -> None:
    lowered = lower_attributes({"gen_ai.operation.name": "execute_tool"})
    assert lowered["openinference.span.kind"] == "TOOL"


def test_langfuse_observation_type_sets_the_kind() -> None:
    """The mapping that stops a Langfuse pipeline normalizing to unclassified spans."""
    lowered = lower_attributes({"langfuse.observation.type": "GENERATION"})
    assert lowered["openinference.span.kind"] == "LLM"


def test_openinference_wins_over_a_foreign_kind() -> None:
    lowered = lower_attributes(
        {"openinference.span.kind": "RETRIEVER", "gen_ai.operation.name": "chat"}
    )
    assert lowered["openinference.span.kind"] == "RETRIEVER"


def test_gen_ai_tokens_lower_and_total_is_derived() -> None:
    lowered = lower_attributes({"gen_ai.usage.input_tokens": 100, "gen_ai.usage.output_tokens": 20})
    assert lowered["llm.token_count.prompt"] == 100
    assert lowered["llm.token_count.completion"] == 20
    assert lowered["llm.token_count.total"] == 120


def test_a_total_is_never_fabricated_from_one_half() -> None:
    lowered = lower_attributes({"gen_ai.usage.input_tokens": 100})
    assert "llm.token_count.total" not in lowered


def test_langfuse_usage_details_lower_from_json_text() -> None:
    lowered = lower_attributes(
        {"langfuse.observation.usage_details": '{"input": 7, "output": 3, "total": 10}'}
    )
    assert lowered["llm.token_count.prompt"] == 7
    assert lowered["llm.token_count.total"] == 10


def test_unparseable_usage_is_skipped_rather_than_guessed() -> None:
    lowered = lower_attributes({"langfuse.observation.usage_details": "not json"})
    assert "llm.token_count.prompt" not in lowered


def test_gen_ai_messages_lower_onto_openinference_message_keys() -> None:
    lowered = lower_attributes(
        {
            "gen_ai.prompt.0.role": "user",
            "gen_ai.prompt.0.content": "hello",
            "gen_ai.completion.0.tool_calls.0.arguments": "{}",
            "gen_ai.completion.0.finish_reason": "stop",
        }
    )
    assert lowered["llm.input_messages.0.message.role"] == "user"
    assert lowered["llm.input_messages.0.message.content"] == "hello"
    key = "llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments"
    assert lowered[key] == "{}"
    # An unknown leaf stays on the bag rather than being invented into the message shape.
    assert "llm.output_messages.0.message.finish_reason" not in lowered


def test_request_params_fold_into_invocation_parameters() -> None:
    lowered = lower_attributes({"gen_ai.request.temperature": 0.2, "gen_ai.request.top_p": 0.9})
    assert lowered["llm.invocation_parameters"] == '{"temperature": 0.2, "top_p": 0.9}'


def test_flatten_turns_nested_attributes_into_dotted_keys() -> None:
    """Phoenix nests; the contract is written flat. An index check on nested data would pass
    vacuously, so this has to happen before grading."""
    flat = flatten({"llm": {"input_messages": [{"message": {"role": "user"}}]}})
    assert flat == {"llm.input_messages.0.message.role": "user"}


def test_an_absent_kind_normalizes_to_span() -> None:
    assert normalize({"span_id": "s", "trace_id": "t"}).span_kind == "SPAN"


def test_status_message_lands_on_the_attribute_bag() -> None:
    """M5 reads the attribute, so a reader that only sets the column must still be seen."""
    result = normalize({"span_id": "s", "trace_id": "t", "status_message": "boom"})
    assert result.attributes["status_message"] == "boom"


def test_parse_time_reads_iso_epoch_seconds_and_nanoseconds() -> None:
    expected = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    assert parse_time("2026-08-05T10:00:00Z") == expected
    assert parse_time(expected.timestamp()) == expected
    assert parse_time(int(expected.timestamp() * 1e9)) == expected


def test_a_naive_timestamp_is_read_as_utc() -> None:
    assert parse_time("2026-08-05T10:00:00").tzinfo == UTC


def test_verify_traffic_is_recognised_by_mark_or_environment() -> None:
    assert span(attributes={"mega.verify": "1"}).is_verify_traffic()
    assert span(attributes={"langfuse.environment": "mega-verify"}).is_verify_traffic()
    assert not span(attributes={"langfuse.environment": "production"}).is_verify_traffic()


def test_only_two_spellings_are_error() -> None:
    """OTel's `UNSET` is OK, and so is anything else — matching upstream exactly.

    Reading extra values as ERROR would make R3 skip spans MEGA Loop still checks, so being
    generous here makes the validator quieter than the product rather than louder.
    """
    from trace_validator.span import normalize_status

    assert normalize_status("ERROR") == "ERROR"
    assert normalize_status("STATUS_CODE_ERROR") == "ERROR"
    for ok in ("UNSET", "OK", "", None, 2, "STATUS_CODE_OK"):
        assert normalize_status(ok) == "OK", ok

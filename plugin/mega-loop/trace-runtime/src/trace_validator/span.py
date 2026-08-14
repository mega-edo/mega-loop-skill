"""The normalized span, and the lowering that produces it.

A platform reader hands us a raw dict; this module turns it into the same `SpanModel` shape
MEGA Loop's ingest would produce, applying the same foreign→OpenInference lowering in the same
order. Checks then run on the lowered span, so the validator judges what the product judges —
not what the developer's SDK happened to emit.

The one rule that governs every mapping: **source data wins**. A foreign key only fills an
OpenInference key that is absent, never one that is already set.
"""

from __future__ import annotations

import json
import re
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from trace_validator import contract as C

_MSG_RE = re.compile(r"^gen_ai\.(prompt|completion)\.(\d+)\.(.+)$")
_TOOL_CALL_LEAF_RE = re.compile(r"^tool_calls\.(\d+)\.(id|name|arguments)$")
_PLAIN_MSG_LEAVES = ("role", "content", "name", "tool_call_id")


class Span(BaseModel):
    """One span, lowered onto the OpenInference contract.

    ``parent_id == ""`` means root — that is the root test used everywhere, including by MEGA
    Loop itself, so an SDK that writes ``"0000000000000000"`` for "no parent" must have it
    cleaned by its reader, not here.
    """

    model_config = ConfigDict(frozen=True)

    span_id: str
    trace_id: str
    name: str = ""
    start_time: datetime
    end_time: datetime
    parent_id: str = ""
    span_kind: str = ""
    status_code: str = "OK"
    status_message: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_root(self) -> bool:
        return not self.parent_id

    def input_value(self) -> str:
        return str(self.attributes.get("input.value") or "").strip()

    def output_value(self) -> str:
        return str(self.attributes.get("output.value") or "").strip()

    def messages(self, prefix: str) -> dict[int, dict[str, str]]:
        """Regroup flattened ``{prefix}.{i}.message.{leaf}`` attributes by message index."""
        plen = len(prefix.split("."))
        out: dict[int, dict[str, str]] = {}
        for key, value in self.attributes.items():
            if not key.startswith(prefix + "."):
                continue
            parts = key.split(".")
            if len(parts) < plen + 2:
                continue
            try:
                idx = int(parts[plen])
            except ValueError:
                continue
            out.setdefault(idx, {})[".".join(parts[plen + 1 :])] = str(value or "")
        return out

    def family_indices(self, prefix: str) -> set[int]:
        plen = len(prefix.split("."))
        found: set[int] = set()
        for key in self.attributes:
            if not key.startswith(prefix + "."):
                continue
            parts = key.split(".")
            if len(parts) <= plen:
                continue
            try:
                found.add(int(parts[plen]))
            except ValueError:
                continue
        return found

    def output_message_contents(self) -> list[str]:
        msgs = self.messages(C.OI_OUT_MESSAGES)
        return [(msgs[i].get("message.content") or "") for i in sorted(msgs)]

    def is_verify_traffic(self) -> bool:
        """MEGA Loop's own verification re-runs, which ingest excludes from detection."""
        if C.VERIFY_MARK_KEY in self.attributes:
            return True
        environment = str(self.attributes.get("langfuse.environment") or "")
        return environment == C.VERIFY_ENVIRONMENT


# --- time ---------------------------------------------------------------------


def parse_time(value: Any) -> datetime:
    """Best-effort timestamp → aware UTC datetime. A naive value is read as UTC."""
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float) and not isinstance(value, bool):
        # OTLP exporters write nanoseconds; SDKs and JSON dumps often write seconds.
        seconds = value / 1e9 if value > 1e12 else float(value)
        return datetime.fromtimestamp(seconds, tz=UTC)
    text = str(value or "").strip()
    if not text:
        return datetime.fromtimestamp(0, tz=UTC)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.fromtimestamp(0, tz=UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# --- attribute flattening -----------------------------------------------------


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Nested attribute payloads → the flat dotted keys the contract is written in.

    Phoenix returns some attribute groups nested; OTLP exporters flatten them. Both must reach
    the checks in one shape, or an index-gap check would see zero indices on a nested payload
    and silently pass.
    """
    flat: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            flat.update(flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(obj, list) and obj and all(isinstance(v, dict | list) for v in obj):
        for i, value in enumerate(obj):
            flat.update(flatten(value, f"{prefix}.{i}"))
    elif prefix:
        flat[prefix] = obj
    return flat


# --- foreign → OpenInference lowering ----------------------------------------


def _set_if_absent(attrs: dict[str, Any], key: str, value: Any) -> None:
    if value is not None and attrs.get(key) is None:
        attrs[key] = value


def _lower_langfuse(attrs: dict[str, Any]) -> None:
    for foreign, target in C.LANGFUSE_SCALARS.items():
        if foreign in attrs:
            _set_if_absent(attrs, target, attrs[foreign])
    usage = attrs.get(C.LF_USAGE)
    if isinstance(usage, str):
        try:
            usage = json.loads(usage)
        except (ValueError, TypeError):
            return  # unparseable: skip rather than guess — never fabricate a token count
    if not isinstance(usage, dict):
        return
    for leaf, target in C.LANGFUSE_USAGE.items():
        value = usage.get(leaf)
        if isinstance(value, int | float) and not isinstance(value, bool):
            _set_if_absent(attrs, target, int(value))


def _derive_total(attrs: dict[str, Any]) -> None:
    """gen_ai has no total-token key — derive one only when both parts are present."""
    if attrs.get(C.OI_TOK_TOTAL) is not None:
        return
    prompt, completion = attrs.get(C.OI_TOK_PROMPT), attrs.get(C.OI_TOK_COMPLETION)
    if prompt is None or completion is None:
        return
    # Non-numeric sources leave the total unset: no total is better than a wrong one.
    with suppress(TypeError, ValueError):
        attrs[C.OI_TOK_TOTAL] = int(prompt) + int(completion)


def _rewrite_msg_leaf(base: str, rest: str) -> str | None:
    tool_call = _TOOL_CALL_LEAF_RE.match(rest)
    if tool_call is not None:
        j, leaf = tool_call.group(1), tool_call.group(2)
        infix = "tool_call.id" if leaf == "id" else f"tool_call.function.{leaf}"
        return f"{base}tool_calls.{j}.{infix}"
    if rest in _PLAIN_MSG_LEAVES:
        return f"{base}{rest}"
    return None  # unknown leaf (finish_reason, refusal, …) — leave it on the bag


def _map_indexed_messages(attrs: dict[str, Any]) -> None:
    for key in list(attrs):
        match = _MSG_RE.match(key)
        if match is None:
            continue
        side, idx, rest = match.group(1), match.group(2), match.group(3)
        family = C.OI_IN_MESSAGES if side == "prompt" else C.OI_OUT_MESSAGES
        target = _rewrite_msg_leaf(f"{family}.{idx}.message.", rest)
        if target is not None:
            _set_if_absent(attrs, target, attrs[key])


def _fold_request_params(attrs: dict[str, Any]) -> None:
    found = {
        key[len(C.REQUEST_PARAM_PREFIX) :]: value
        for key, value in attrs.items()
        if key.startswith(C.REQUEST_PARAM_PREFIX)
        and key[len(C.REQUEST_PARAM_PREFIX) :] in C.REQUEST_PARAM_LEAVES
    }
    if not found:
        return
    existing = attrs.get(C.OI_INVOCATION)
    merged: dict[str, Any] = dict(found)
    if isinstance(existing, str) and existing.strip():
        try:
            prior = json.loads(existing)
        except (ValueError, TypeError):
            return  # don't clobber an unparseable existing value
        if isinstance(prior, dict):
            merged = {**found, **prior}  # existing keys win
    elif isinstance(existing, dict):
        merged = {**found, **existing}
    attrs[C.OI_INVOCATION] = json.dumps(merged, sort_keys=True)


def _lower_kind(attrs: dict[str, Any]) -> None:
    if attrs.get(C.OI_KIND) is not None:
        return
    kind = (
        C.OP_NAME_KIND.get(str(attrs.get("gen_ai.operation.name") or "").lower())
        or C.REQUEST_TYPE_KIND.get(str(attrs.get("llm.request.type") or "").lower())
        or C.TRACELOOP_KIND.get(str(attrs.get("traceloop.span.kind") or "").lower())
        or C.LANGFUSE_KIND.get(str(attrs.get(C.LF_TYPE) or "").lower())
    )
    if kind is not None:
        attrs[C.OI_KIND] = kind


def lower_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Fill OpenInference keys from every foreign family, in MEGA Loop's order.

    The order matters in one place: ``_derive_total`` runs after both token families, so a
    Langfuse ``usage_details`` total is honoured before a derived one is considered.
    """
    attrs = dict(attributes)
    for foreign, target in C.SCALAR_TOKENS.items():
        if foreign in attrs:
            _set_if_absent(attrs, target, attrs[foreign])
    _lower_langfuse(attrs)
    _derive_total(attrs)
    for source in C.MODEL_SOURCES:
        if attrs.get(C.OI_MODEL) is not None:
            break
        _set_if_absent(attrs, C.OI_MODEL, attrs.get(source))
    _map_indexed_messages(attrs)
    _fold_request_params(attrs)
    _lower_kind(attrs)
    return attrs


def normalize_status(value: Any) -> str:
    """Only these two spellings are ERROR — everything else, including OTel's ``UNSET``, is OK.

    Upstream's list is exactly this, and matching it matters in a direction that is easy to get
    backwards: reading more values as ERROR would make R3 skip spans MEGA Loop still checks,
    so a too-generous reading here makes the validator quieter than the product, not louder.
    """
    text = str(value or "OK").strip().upper()
    return "ERROR" if text in ("ERROR", "STATUS_CODE_ERROR") else "OK"


def normalize(raw: dict[str, Any]) -> Span:
    """Raw reader dict → `Span`, mirroring `OpenInferenceNormalizer.normalize`."""
    context = raw.get("context") or {}
    attributes = lower_attributes(flatten(raw.get("attributes") or {}))
    kind = (
        raw.get("span_kind") or attributes.get(C.OI_KIND) or attributes.get("span.kind") or "SPAN"
    )
    status_message = str(raw.get("status_message") or "")
    if status_message and "status_message" not in attributes:
        attributes["status_message"] = status_message
    return Span(
        span_id=str(context.get("span_id") or raw.get("span_id") or ""),
        trace_id=str(context.get("trace_id") or raw.get("trace_id") or ""),
        name=str(raw.get("name") or ""),
        start_time=parse_time(raw.get("start_time")),
        end_time=parse_time(raw.get("end_time")),
        parent_id=str(raw.get("parent_id") or ""),
        span_kind=str(kind).upper(),
        status_code=normalize_status(raw.get("status_code")),
        status_message=status_message,
        attributes=attributes,
    )

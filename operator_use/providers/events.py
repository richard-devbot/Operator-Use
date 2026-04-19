from enum import StrEnum
from pydantic import BaseModel

from operator_use.providers.views import TokenUsage


class LLMStreamEventType(StrEnum):
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    TOOL_CALL = "tool_call"
    THINK_START = "think_start"
    THINK_DELTA = "think_delta"
    THINK_END = "think_end"
    ERROR = "error"


class LLMEventType(StrEnum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    ERROR = "error"


class StopReason(StrEnum):
    END_TURN = "end_turn"           # normal completion
    MAX_TOKENS = "max_tokens"       # hit token/context limit
    TOOL_CALL = "tool_call"         # tool/function call requested
    STOP_SEQUENCE = "stop_sequence" # custom stop sequence triggered
    CONTENT_FILTER = "content_filter"  # safety / content policy filter
    ERROR = "error"                 # provider error
    UNKNOWN = "unknown"             # unmapped / not provided


def map_openai_stop_reason(raw: str | None) -> StopReason:
    return {
        "stop": StopReason.END_TURN,
        "length": StopReason.MAX_TOKENS,
        "tool_calls": StopReason.TOOL_CALL,
        "function_call": StopReason.TOOL_CALL,
        "content_filter": StopReason.CONTENT_FILTER,
        "error": StopReason.ERROR,
    }.get(raw or "", StopReason.UNKNOWN)


def map_anthropic_stop_reason(raw: str | None) -> StopReason:
    return {
        "end_turn": StopReason.END_TURN,
        "max_tokens": StopReason.MAX_TOKENS,
        "stop_sequence": StopReason.STOP_SEQUENCE,
        "tool_use": StopReason.TOOL_CALL,
    }.get(raw or "", StopReason.UNKNOWN)


def map_google_stop_reason(raw: object) -> StopReason:
    if raw is None:
        return StopReason.UNKNOWN
    name = raw.name if hasattr(raw, "name") else str(raw)
    return {
        "STOP": StopReason.END_TURN,
        "MAX_TOKENS": StopReason.MAX_TOKENS,
        "SAFETY": StopReason.CONTENT_FILTER,
        "RECITATION": StopReason.CONTENT_FILTER,
        "BLOCKLIST": StopReason.CONTENT_FILTER,
        "PROHIBITED_CONTENT": StopReason.CONTENT_FILTER,
        "SPII": StopReason.CONTENT_FILTER,
        "MALFORMED_FUNCTION_CALL": StopReason.ERROR,
        "OTHER": StopReason.UNKNOWN,
        "FINISH_REASON_UNSPECIFIED": StopReason.UNKNOWN,
    }.get(name, StopReason.UNKNOWN)


class Thinking(BaseModel):
    """Thinking/reasoning content with optional cryptographic signature (Anthropic)."""

    content: str | None = None
    signature: str | bytes | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    params: dict


class LLMStreamEvent(BaseModel):
    type: LLMStreamEventType
    thinking: Thinking | None = None
    content: str | None = None
    tool_call: ToolCall | None = None
    usage: TokenUsage | None = None
    stop_reason: StopReason | None = None


class LLMEvent(BaseModel):
    type: LLMEventType
    thinking: Thinking | None = None
    content: str | None = None
    tool_call: ToolCall | None = None
    usage: TokenUsage | None = None
    error: str | None = None
    stop_reason: StopReason | None = None

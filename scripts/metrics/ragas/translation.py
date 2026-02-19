"""Translation layer between RAGAS experiment dict rows and typed schema models."""

from typing import Any

from schema.models import ExecutedStep, Reference, ToolCall, Turn


def dict_to_executed_step(row: dict[str, Any]) -> ExecutedStep:
    """Convert a RAGAS experiment dict row to an ExecutedStep.

    Handles both single-turn (user_input is str) and multi-turn
    (user_input is list of message dicts) formats.

    Args:
        row: Dictionary from RAGAS experiment JSONL.

    Returns:
        ExecutedStep with fields mapped from the dict.
    """
    user_input = row.get("user_input", "")
    turns: list[Turn] | None = None
    step_input: str

    if isinstance(user_input, list):
        # Multi-turn: first human message becomes input, full list becomes turns
        step_input = ""
        parsed_turns: list[Turn] = []
        for msg in user_input:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                msg_type = msg.get("type", "human")
                # Normalize 'ai' to 'agent' to match Turn's Literal type
                if msg_type == "ai":
                    msg_type = "agent"
                if msg_type not in ("human", "agent", "tool"):
                    msg_type = "human"
                parsed_turns.append(Turn(content=content, type=msg_type))  # type: ignore[arg-type]
                if not step_input and msg_type == "human":
                    step_input = content
            else:
                parsed_turns.append(Turn(content=str(msg), type="human"))
                if not step_input:
                    step_input = str(msg)
        turns = parsed_turns if parsed_turns else None
    else:
        step_input = str(user_input)

    # Map turns from row if present (e.g. from multi-turn experiment output)
    if turns is None and "turns" in row and isinstance(row["turns"], list):
        parsed_turns = []
        for t in row["turns"]:
            if isinstance(t, dict):
                t_type = t.get("type", "human")
                if t_type == "ai":
                    t_type = "agent"
                if t_type not in ("human", "agent", "tool"):
                    t_type = "human"
                parsed_turns.append(Turn(content=t.get("content", ""), type=t_type))  # type: ignore[arg-type]
        turns = parsed_turns if parsed_turns else None

    # Build reference
    reference: Reference | None = None
    ref_response = row.get("reference")
    ref_tool_calls_raw = row.get("reference_tool_calls")

    if ref_response is not None or ref_tool_calls_raw is not None:
        ref_tool_calls: list[ToolCall] | None = None
        if isinstance(ref_tool_calls_raw, list):
            ref_tool_calls = [
                ToolCall(name=tc.get("name", ""), args=tc.get("args", tc.get("arguments")) or {})
                for tc in ref_tool_calls_raw
                if isinstance(tc, dict)
            ]
        reference = Reference(
            response=str(ref_response) if ref_response is not None else None,
            tool_calls=ref_tool_calls,
        )

    # Store RAGAS-specific fields in custom_values
    custom_values: dict[str, Any] = {}
    if "response" in row:
        custom_values["response"] = row["response"]
    if "retrieved_contexts" in row:
        custom_values["retrieved_contexts"] = row["retrieved_contexts"]

    # Preserve any other custom fields
    known_keys = {
        "user_input",
        "response",
        "retrieved_contexts",
        "reference",
        "reference_tool_calls",
        "turns",
        "sample_hash",
        "id",
        "trace_id",
    }
    for key, value in row.items():
        if key not in known_keys and key not in custom_values:
            custom_values[key] = value

    step_id = row.get("id") or row.get("sample_hash")

    return ExecutedStep(
        input=step_input,
        reference=reference,
        custom_values=custom_values if custom_values else None,
        id=str(step_id) if step_id else None,
        turns=turns,
    )

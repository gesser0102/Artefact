from collections.abc import Sequence

from emporio_agent.application.conversation.messages import ChatMessage, Role

MAX_HISTORY_MESSAGES = 30


def trimmed_history(messages: Sequence[ChatMessage]) -> tuple[ChatMessage, ...]:
    start = max(len(messages) - MAX_HISTORY_MESSAGES, 0)
    while start < len(messages) and messages[start].role is Role.TOOL:
        start += 1
    return tuple(messages[start:])


def model_input(
    system_message: ChatMessage,
    messages: Sequence[ChatMessage],
) -> tuple[ChatMessage, ...]:
    return (system_message, *trimmed_history(messages))

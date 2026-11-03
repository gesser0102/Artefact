from emporio_agent.agent.history import MAX_HISTORY_MESSAGES, model_input, trimmed_history
from emporio_agent.application.conversation.messages import ChatMessage, Role
from fakes import tool_call

SYSTEM = ChatMessage(Role.SYSTEM, "prompt")


def user(text: str) -> ChatMessage:
    return ChatMessage(Role.USER, text)


def tool_round(index: int, results: int) -> list[ChatMessage]:
    calls = tuple(tool_call("list_categories", "{}", f"c{index}_{n}") for n in range(results))
    return [
        ChatMessage(Role.ASSISTANT, None, tool_calls=calls),
        *[ChatMessage(Role.TOOL, "{}", tool_call_id=call.call_id) for call in calls],
    ]


def test_short_history_is_kept_whole():
    messages = [user("a"), ChatMessage(Role.ASSISTANT, "b")]

    assert trimmed_history(messages) == tuple(messages)
    assert model_input(SYSTEM, messages) == (SYSTEM, *messages)


def test_long_history_keeps_the_most_recent_messages():
    messages = [user(str(index)) for index in range(MAX_HISTORY_MESSAGES + 10)]

    kept = trimmed_history(messages)

    assert len(kept) == MAX_HISTORY_MESSAGES
    assert kept[-1] == messages[-1]


def test_window_never_starts_inside_a_tool_round():
    tail = [*tool_round(1, 3), *[user(str(index)) for index in range(MAX_HISTORY_MESSAGES - 6)]]
    filler = [user(str(index)) for index in range(5)]
    messages = [*filler, *tool_round(0, 4), *tail]
    cut = len(messages) - MAX_HISTORY_MESSAGES
    assert messages[cut].role is Role.TOOL

    kept = trimmed_history(messages)

    assert kept[0].role is not Role.TOOL
    assert len(kept) < MAX_HISTORY_MESSAGES
    assert kept[-len(tail) :] == tuple(tail)


def test_history_of_only_tool_messages_trims_to_empty():
    messages = [ChatMessage(Role.TOOL, "{}", tool_call_id=str(n)) for n in range(40)]

    assert trimmed_history(messages) == ()

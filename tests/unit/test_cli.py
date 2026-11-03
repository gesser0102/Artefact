import io
from pathlib import Path

import pytest

from emporio_agent.agent.conversation import TurnResult
from emporio_agent.agent.tracing import ModelTrace, ToolOutcome, ToolTrace, TurnTrace
from emporio_agent.cli import (
    DATA_LOAD_MESSAGE,
    EXIT_FAILURE,
    EXIT_MISSING_API_KEY,
    EXIT_OK,
    FAREWELL,
    GREETING,
    MISSING_KEY_MESSAGE,
    NEW_SESSION_NOTICE,
    CliOptions,
    main,
    redact_personal_data,
    run,
    script_messages,
)
from emporio_agent.config import Settings
from emporio_agent.domain.redaction import REDACTED

CUSTOMER_PHONE = "(67) 99812-3456"
TRACE = TurnTrace(
    (
        ModelTrace("modelo-a", 1200, 40, 800, 1),
        ToolTrace("get_order_status", {"order_id": 7, "phone": REDACTED}, 3, ToolOutcome.OK, 90),
        ModelTrace("modelo-a", 1300, 60, 900, 0),
    )
)


class FakeSession:
    def __init__(self, number: int, received: list[tuple[int, str]]) -> None:
        self.number = number
        self.received = received

    def reply(self, user_text: str) -> TurnResult:
        self.received.append((self.number, user_text))
        return TurnResult(text=f"resposta {self.number}: {user_text}", trace=TRACE)


class FakeAgent:
    def __init__(self) -> None:
        self.sessions = 0
        self.received: list[tuple[int, str]] = []

    def start_session(self) -> FakeSession:
        self.sessions += 1
        return FakeSession(self.sessions, self.received)


def options(
    trace: bool = False,
    script: Path | None = None,
    transcript: Path | None = None,
) -> CliOptions:
    return CliOptions(trace=trace, debug=False, script=script, transcript=transcript)


def reader(*lines: str):
    pending = list(lines)

    def read_line(prompt: str) -> str:
        if not pending:
            raise EOFError
        return pending.pop(0)

    return read_line


def run_cli(agent: FakeAgent, cli_options: CliOptions, *lines: str) -> tuple[int, str, str]:
    output, errors = io.StringIO(), io.StringIO()
    code = run(cli_options, agent, reader(*lines), output, errors)
    return code, output.getvalue(), errors.getvalue()


def test_interactive_loop_greets_replies_and_exits_with_sair():
    agent = FakeAgent()

    code, output, errors = run_cli(agent, options(), "oi", "   ", "/sair", "nunca lida")

    assert code == EXIT_OK
    assert output.splitlines() == [
        f"Lia: {GREETING}",
        "Lia: resposta 1: oi",
        f"Lia: {FAREWELL}",
    ]
    assert agent.received == [(1, "oi")]
    assert errors == ""


def test_end_of_input_exits_cleanly():
    code, output, _ = run_cli(FakeAgent(), options(), "oi")

    assert code == EXIT_OK
    assert output.endswith("resposta 1: oi\n\n")


def test_keyboard_interrupt_exits_cleanly():
    def interrupted(prompt: str) -> str:
        raise KeyboardInterrupt

    output = io.StringIO()

    assert run(options(), FakeAgent(), interrupted, output, io.StringIO()) == EXIT_OK


def test_nova_starts_a_fresh_session():
    agent = FakeAgent()

    _, output, _ = run_cli(agent, options(), "a", "/nova", "b")

    assert agent.sessions == 2
    assert agent.received == [(1, "a"), (2, "b")]
    assert f"Lia: {NEW_SESSION_NOTICE} {GREETING}" in output.splitlines()


def test_trace_flag_prints_a_compact_trace_to_stderr():
    _, output, errors = run_cli(FakeAgent(), options(trace=True), "pedido 7")

    assert "[trace] tokens 2500+100 retries 1" in errors
    assert "get_order_status" in errors
    assert REDACTED in errors
    assert "modelo-a tokens 1200+40" in errors
    assert "[trace]" not in output


def test_script_messages_skip_blank_and_comment_lines():
    lines = ["# roteiro", "", "oi, vocês abrem domingo?", "   ", "  tem violão yamaha?  "]

    assert script_messages(lines) == ["oi, vocês abrem domingo?", "tem violão yamaha?"]


def test_script_mode_runs_without_reading_input(tmp_path):
    script = tmp_path / "roteiro.txt"
    script.write_text("# comentário\noi\n\ntem violão?\n/sair\ndepois\n", encoding="utf-8")
    agent = FakeAgent()

    code, output, _ = run_cli(agent, options(script=script))

    assert code == EXIT_OK
    assert output.splitlines() == [
        f"Lia: {GREETING}",
        "Você: oi",
        "Lia: resposta 1: oi",
        "Você: tem violão?",
        "Lia: resposta 1: tem violão?",
        "Você: /sair",
        f"Lia: {FAREWELL}",
    ]


def test_unreadable_script_fails_with_exit_one(tmp_path):
    script = tmp_path / "latin1.txt"
    script.write_bytes("ação".encode("latin-1"))

    code, _, errors = run_cli(FakeAgent(), options(script=script))

    assert code == EXIT_FAILURE
    assert "roteiro" in errors


def test_transcript_is_written_as_markdown(tmp_path):
    transcript = tmp_path / "saida" / "conversa.md"

    run_cli(
        FakeAgent(),
        options(transcript=transcript),
        f"meu telefone é {CUSTOMER_PHONE}",
        "/nova",
        "oi",
    )

    content = transcript.read_text(encoding="utf-8")
    assert content.startswith("# Conversa com a Lia")
    assert f"**Lia:** {GREETING}" in content
    assert f"**Cliente:** meu telefone é {REDACTED}" in content
    assert "**Lia:** resposta 2: oi" in content
    assert "<details><summary>Ferramentas: get_order_status · tokens 2500+100" in content
    assert '- `get_order_status` `{"order_id": 7, "phone": "[redacted]"}` (ok)' in content
    assert "</details>" in content
    assert "_Nova conversa_" in content
    assert "99812" not in content


def test_transcript_keeps_the_official_contact_but_redacts_customer_data():
    text = f"Fale com a equipe no (67) 3341-4444; seu número {CUSTOMER_PHONE} está anotado."

    assert redact_personal_data(text) == (
        f"Fale com a equipe no (67) 3341-4444; seu número {REDACTED} está anotado."
    )


def test_missing_key_exits_with_code_two(monkeypatch, data_dir):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("EMPORIO_GROQ_API_KEY", raising=False)
    errors = io.StringIO()

    code = main(
        [],
        settings=Settings(_env_file=None, data_dir=data_dir),
        read_line=reader(),
        output=io.StringIO(),
        errors=errors,
    )

    assert code == EXIT_MISSING_API_KEY
    assert errors.getvalue() == f"{MISSING_KEY_MESSAGE}\n"
    assert "GROQ_API_KEY" in MISSING_KEY_MESSAGE
    assert ".env" in MISSING_KEY_MESSAGE


def test_data_load_failure_exits_with_code_one(tmp_path):
    errors = io.StringIO()

    code = main(
        [],
        settings=Settings(_env_file=None, data_dir=tmp_path / "nada", groq_api_key="gsk_falsa"),
        read_line=reader(),
        output=io.StringIO(),
        errors=errors,
    )

    assert code == EXIT_FAILURE
    assert errors.getvalue() == f"{DATA_LOAD_MESSAGE}\n"


def test_main_runs_the_real_wiring_until_end_of_input(data_dir):
    output = io.StringIO()

    code = main(
        ["--debug"],
        settings=Settings(_env_file=None, data_dir=data_dir, groq_api_key="gsk_falsa"),
        read_line=reader("/sair"),
        output=output,
        errors=io.StringIO(),
    )

    assert code == EXIT_OK
    assert output.getvalue().splitlines() == [f"Lia: {GREETING}", f"Lia: {FAREWELL}"]


@pytest.mark.parametrize("flag", ["--ajuda-invalida"])
def test_unknown_flags_are_rejected(flag):
    with pytest.raises(SystemExit):
        main([flag], settings=Settings(_env_file=None))

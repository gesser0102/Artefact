import argparse
import io
import json
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from pydantic import ValidationError

from emporio_agent.agent.conversation import TurnResult
from emporio_agent.agent.prompts import OFFICIAL_CONTACT
from emporio_agent.agent.tracing import ModelTrace, ToolTrace, TurnTrace
from emporio_agent.bootstrap import build_container
from emporio_agent.config import Settings, invalid_variable_names
from emporio_agent.domain.exceptions import DataLoadError
from emporio_agent.domain.redaction import redact_text

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_MISSING_API_KEY = 2
EXIT_INVALID_CONFIG = 3
PROGRAM_NAME = "python -m emporio_agent"
CUSTOMER_PREFIX = "Você: "
AGENT_PREFIX = "Lia: "
EXIT_COMMAND = "/sair"
NEW_SESSION_COMMAND = "/nova"
COMMENT_PREFIX = "#"
UTF8 = "utf-8"
UTF8_SIG = "utf-8-sig"
ENCODING_ERRORS = "replace"
VARIABLE_SEPARATOR = ", "
GREETING = "Oi! Eu sou a Lia, assistente virtual da Empório da Música. Como posso te ajudar hoje?"
FAREWELL = "Foi um prazer falar com você! Até a próxima."
NEW_SESSION_NOTICE = "Começando uma nova conversa."
MISSING_KEY_MESSAGE = (
    "Não encontrei a chave da Groq. Defina GROQ_API_KEY no arquivo .env na raiz do projeto "
    "(uma linha GROQ_API_KEY=<sua chave>) e rode de novo."
)
DATA_LOAD_MESSAGE = (
    "Não consegui carregar os dados da loja (catálogo, pedidos ou políticas). "
    "Verifique a pasta de dados e tente de novo."
)
INVALID_CONFIG_MESSAGE = (
    "A configuração tem valores inválidos em: {variables}. Corrija essas variáveis no arquivo "
    ".env ou no ambiente e rode de novo."
)
ENV_FILE_ENCODING_MESSAGE = (
    "Não consegui ler o arquivo .env: ele precisa estar salvo como texto UTF-8. "
    "Salve o arquivo de novo nessa codificação e rode de novo."
)
INPUT_DECODE_MESSAGE = "Não consegui ler a entrada como texto UTF-8. Encerrando a conversa."
SCRIPT_READ_MESSAGE = "Não consegui ler o roteiro {path} como texto UTF-8."
TRANSCRIPT_WRITE_MESSAGE = "Não consegui gravar a transcrição em {path}."
TRANSCRIPT_TITLE = "# Conversa com a Lia — Empório da Música"
TRANSCRIPT_NEW_SESSION = "---\n\n_Nova conversa_"
NO_TOOLS_LABEL = "nenhuma ferramenta"


class ChatSession(Protocol):
    def reply(self, user_text: str) -> TurnResult: ...


class ChatAgent(Protocol):
    def start_session(self) -> ChatSession: ...


type LineReader = Callable[[str], str]


@dataclass(frozen=True)
class CliOptions:
    trace: bool
    debug: bool
    script: Path | None
    transcript: Path | None


def parse_options(argv: Sequence[str] | None) -> CliOptions:
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Converse com a Lia, assistente virtual da Empório da Música.",
    )
    parser.add_argument("--trace", action="store_true", help="mostra ferramentas e tokens")
    parser.add_argument("--debug", action="store_true", help="liga o log detalhado")
    parser.add_argument("--script", type=Path, help="arquivo com uma mensagem por linha")
    parser.add_argument("--transcript", type=Path, help="grava a conversa em Markdown")
    namespace = parser.parse_args(argv)
    return CliOptions(
        trace=namespace.trace,
        debug=namespace.debug,
        script=namespace.script,
        transcript=namespace.transcript,
    )


def arguments_text(step: ToolTrace) -> str:
    return json.dumps(step.arguments, ensure_ascii=False, sort_keys=True)


def format_tool_step(step: ToolTrace) -> str:
    return (
        f"  tool  {step.name} {arguments_text(step)} -> {step.outcome.value} "
        f"{step.output_chars} chars {step.duration_ms} ms"
    )


def format_model_step(step: ModelTrace) -> str:
    return (
        f"  model {step.model} tokens {step.prompt_tokens}+{step.completion_tokens} "
        f"retries {step.retries} {step.duration_ms} ms"
    )


def format_trace(trace: TurnTrace) -> str:
    lines = [
        f"[trace] tokens {trace.prompt_tokens}+{trace.completion_tokens} "
        f"retries {trace.retries} {trace.duration_ms} ms"
    ]
    for step in trace.steps:
        lines.append(
            format_tool_step(step) if isinstance(step, ToolTrace) else format_model_step(step)
        )
    return "\n".join(lines)


def transcript_tool_line(step: ToolTrace) -> str:
    return f"- `{step.name}` `{arguments_text(step)}` ({step.outcome.value})"


def transcript_details(trace: TurnTrace) -> str:
    tool_steps = trace.tool_steps
    names = ", ".join(step.name for step in tool_steps) or NO_TOOLS_LABEL
    tool_lines = [transcript_tool_line(step) for step in tool_steps] or [f"- {NO_TOOLS_LABEL}"]
    summary = (
        f"Ferramentas: {names} · tokens {trace.prompt_tokens}+{trace.completion_tokens} "
        f"· retries {trace.retries}"
    )
    return "\n".join([f"<details><summary>{summary}</summary>", "", *tool_lines, "", "</details>"])


def redact_personal_data(text: str) -> str:
    return OFFICIAL_CONTACT.join(redact_text(part) for part in text.split(OFFICIAL_CONTACT))


class Transcript:
    def __init__(self) -> None:
        self._blocks: list[str] = [TRANSCRIPT_TITLE]

    def add_agent(self, text: str) -> None:
        self._blocks.append(f"**Lia:** {redact_personal_data(text)}")

    def add_customer(self, text: str) -> None:
        self._blocks.append(f"**Cliente:** {redact_personal_data(text)}")

    def add_turn(self, text: str, result: TurnResult) -> None:
        self.add_customer(text)
        self.add_agent(result.text)
        self._blocks.append(transcript_details(result.trace))

    def add_new_session(self) -> None:
        self._blocks.append(TRANSCRIPT_NEW_SESSION)

    def render(self) -> str:
        return "\n\n".join(self._blocks) + "\n"


class Dialogue:
    def __init__(
        self,
        agent: ChatAgent,
        output: TextIO,
        errors: TextIO,
        show_trace: bool,
    ) -> None:
        self._agent = agent
        self._output = output
        self._errors = errors
        self._show_trace = show_trace
        self._session = agent.start_session()
        self.transcript = Transcript()
        self._say(GREETING)

    def handle(self, text: str) -> bool:
        message = text.strip()
        if not message:
            return True
        if message == EXIT_COMMAND:
            self._say(FAREWELL)
            return False
        if message == NEW_SESSION_COMMAND:
            self._start_new_session()
            return True
        result = self._session.reply(message)
        self.transcript.add_turn(message, result)
        self._output.write(f"{AGENT_PREFIX}{result.text}\n")
        self._output.flush()
        if self._show_trace:
            self._errors.write(f"{format_trace(result.trace)}\n")
            self._errors.flush()
        return True

    def _start_new_session(self) -> None:
        self._session = self._agent.start_session()
        self.transcript.add_new_session()
        self._say(f"{NEW_SESSION_NOTICE} {GREETING}")

    def _say(self, text: str) -> None:
        self.transcript.add_agent(text)
        self._output.write(f"{AGENT_PREFIX}{text}\n")
        self._output.flush()


def script_messages(lines: Iterable[str]) -> list[str]:
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith(COMMENT_PREFIX)
    ]


def run_script(dialogue: Dialogue, messages: Iterable[str], output: TextIO) -> None:
    try:
        for message in messages:
            output.write(f"{CUSTOMER_PREFIX}{message}\n")
            output.flush()
            if not dialogue.handle(message):
                return
    except KeyboardInterrupt:
        output.write("\n")


def run_interactive(
    dialogue: Dialogue,
    read_line: LineReader,
    output: TextIO,
    errors: TextIO,
) -> None:
    try:
        while dialogue.handle(read_line(CUSTOMER_PREFIX)):
            pass
    except (EOFError, KeyboardInterrupt):
        output.write("\n")
    except UnicodeDecodeError:
        output.write("\n")
        errors.write(f"{INPUT_DECODE_MESSAGE}\n")


def read_script(path: Path, errors: TextIO) -> list[str] | None:
    try:
        return script_messages(path.read_text(encoding=UTF8_SIG).splitlines())
    except (OSError, UnicodeDecodeError):
        errors.write(f"{SCRIPT_READ_MESSAGE.format(path=path)}\n")
        return None


def write_transcript(path: Path, transcript: Transcript, errors: TextIO) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(transcript.render(), encoding=UTF8)
    except OSError:
        errors.write(f"{TRANSCRIPT_WRITE_MESSAGE.format(path=path)}\n")
        return False
    return True


def run(
    options: CliOptions,
    agent: ChatAgent,
    read_line: LineReader,
    output: TextIO,
    errors: TextIO,
) -> int:
    messages = None if options.script is None else read_script(options.script, errors)
    if options.script is not None and messages is None:
        return EXIT_FAILURE
    dialogue = Dialogue(agent, output, errors, options.trace)
    try:
        if messages is None:
            run_interactive(dialogue, read_line, output, errors)
        else:
            run_script(dialogue, messages, output)
    finally:
        transcript_ok = options.transcript is None or write_transcript(
            options.transcript, dialogue.transcript, errors
        )
    return EXIT_OK if transcript_ok else EXIT_FAILURE


def use_utf8_streams() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding=UTF8, errors=ENCODING_ERRORS)


def invalid_config_message(error: ValidationError) -> str:
    variables = VARIABLE_SEPARATOR.join(invalid_variable_names(error))
    return INVALID_CONFIG_MESSAGE.format(variables=variables)


def load_settings(errors: TextIO) -> Settings | None:
    try:
        return Settings()
    except ValidationError as error:
        errors.write(f"{invalid_config_message(error)}\n")
    except UnicodeDecodeError:
        errors.write(f"{ENV_FILE_ENCODING_MESSAGE}\n")
    return None


def main(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
    read_line: LineReader = input,
    output: TextIO | None = None,
    errors: TextIO | None = None,
) -> int:
    use_utf8_streams()
    output_stream = sys.stdout if output is None else output
    error_stream = sys.stderr if errors is None else errors
    options = parse_options(argv)
    configured = load_settings(error_stream) if settings is None else settings
    if configured is None:
        return EXIT_INVALID_CONFIG
    if options.debug:
        configured = configured.model_copy(update={"debug": True})
    if configured.groq_api_key is None:
        error_stream.write(f"{MISSING_KEY_MESSAGE}\n")
        return EXIT_MISSING_API_KEY
    try:
        container = build_container(configured)
    except DataLoadError:
        error_stream.write(f"{DATA_LOAD_MESSAGE}\n")
        return EXIT_FAILURE
    if container.agent is None:
        error_stream.write(f"{MISSING_KEY_MESSAGE}\n")
        return EXIT_MISSING_API_KEY
    return run(options, container.agent, read_line, output_stream, error_stream)

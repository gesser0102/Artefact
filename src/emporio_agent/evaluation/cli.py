import argparse
import io
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from emporio_agent.application.ports import ErrorReporter
from emporio_agent.bootstrap import build_container
from emporio_agent.config import Settings
from emporio_agent.domain.exceptions import DataLoadError, EvalCaseError
from emporio_agent.evaluation.cases import load_cases, select_cases
from emporio_agent.evaluation.report import render_json, render_markdown, summarize, summary_line
from emporio_agent.evaluation.resolver import EvalDataResolver
from emporio_agent.evaluation.runner import CaseRecord, ChatAgent, EvalRunner, Sleeper

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_MISSING_API_KEY = 2
PROGRAM_NAME = "python -m emporio_agent.evaluation"
DEFAULT_CASES_PATH = Path("evals/cases.json")
DEFAULT_OUTPUT_DIR = Path("evals/results")
DEFAULT_PAUSE_SECONDS = 20.0
MARKDOWN_REPORT_NAME = "latest.md"
JSON_REPORT_NAME = "latest.json"
ID_SEPARATOR = ","
UTF8 = "utf-8"
MISSING_KEY_MESSAGE = "GROQ_API_KEY is not set; add it to .env at the project root and retry."
DATA_LOAD_MESSAGE = "Could not load the store data (catalog, orders or policies)."
CASES_ERROR_MESSAGE = "Invalid evaluation cases: {error}"
REPORT_WRITE_MESSAGE = "Could not write the reports to {path}."
CASE_PROGRESS = "[{number}/{total}] {case_id} {result}"
PASS_LABEL = "PASS"
FAIL_LABEL = "FAIL"

type Now = Callable[[], datetime]


@dataclass(frozen=True)
class EvalOptions:
    cases: Path
    only: tuple[str, ...]
    category: str | None
    pause: float
    out: Path


@dataclass(frozen=True)
class EvalDependencies:
    agent: ChatAgent
    resolver: EvalDataResolver
    report_error: ErrorReporter
    primary_model: str
    now: Now


def split_ids(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(part.strip() for part in raw.split(ID_SEPARATOR) if part.strip())


def parse_options(argv: Sequence[str] | None) -> EvalOptions:
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Run the Lia evaluation cases against the real model.",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--category")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SECONDS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR)
    namespace = parser.parse_args(argv)
    return EvalOptions(
        cases=namespace.cases,
        only=split_ids(namespace.only),
        category=namespace.category,
        pause=max(namespace.pause, 0.0),
        out=namespace.out,
    )


def progress_printer(total: int, errors: TextIO) -> Callable[[CaseRecord], None]:
    finished: list[CaseRecord] = []

    def print_progress(record: CaseRecord) -> None:
        finished.append(record)
        result = PASS_LABEL if record.passed else FAIL_LABEL
        errors.write(
            CASE_PROGRESS.format(
                number=len(finished), total=total, case_id=record.case_id, result=result
            )
            + "\n"
        )
        errors.flush()

    return print_progress


def write_reports(out: Path, markdown: str, json_text: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKDOWN_REPORT_NAME).write_text(markdown, encoding=UTF8)
    (out / JSON_REPORT_NAME).write_text(json_text, encoding=UTF8)


def run_evaluation(
    options: EvalOptions,
    dependencies: EvalDependencies,
    output: TextIO,
    errors: TextIO,
    sleep: Sleeper,
) -> int:
    try:
        cases = select_cases(
            load_cases(options.cases, dependencies.report_error), options.only, options.category
        )
        dependencies.resolver.validate(cases)
    except EvalCaseError as error:
        errors.write(f"{CASES_ERROR_MESSAGE.format(error=error)}\n")
        return EXIT_FAILURE
    runner = EvalRunner(
        dependencies.agent,
        dependencies.resolver,
        options.pause,
        sleep,
        on_case=progress_printer(len(cases), errors),
    )
    records = runner.run(cases)
    summary = summarize(records, dependencies.primary_model, dependencies.now())
    try:
        write_reports(options.out, render_markdown(records, summary), render_json(records, summary))
    except OSError as error:
        dependencies.report_error("evaluation.report", error, path=str(options.out))
        errors.write(f"{REPORT_WRITE_MESSAGE.format(path=options.out)}\n")
        return EXIT_FAILURE
    output.write(f"{summary_line(summary)} -> {options.out / MARKDOWN_REPORT_NAME}\n")
    output.flush()
    return EXIT_OK


def use_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding=UTF8)


def main(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
    output: TextIO | None = None,
    errors: TextIO | None = None,
    sleep: Sleeper = time.sleep,
) -> int:
    use_utf8_streams()
    output_stream = sys.stdout if output is None else output
    error_stream = sys.stderr if errors is None else errors
    options = parse_options(argv)
    configured = Settings() if settings is None else settings
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
    dependencies = EvalDependencies(
        agent=container.agent,
        resolver=EvalDataResolver(container.repository, container.repository.list_customers()),
        report_error=container.tools.report_error,
        primary_model=configured.model,
        now=container.clock.now,
    )
    return run_evaluation(options, dependencies, output_stream, error_stream, sleep)

import pytest

from emporio_agent.agent.tracing import redact_arguments, redact_value
from emporio_agent.domain.redaction import REDACTED

PHONE = "(67) 99812-3456"
DIGITS = "67998123456"


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"phone": "qualquer"}, {"phone": REDACTED}),
        ({"Telefone": 1}, {"Telefone": REDACTED}),
        ({"email": "a@b.com"}, {"email": REDACTED}),
        ({"query": f"ligar {PHONE}"}, {"query": f"ligar {REDACTED}"}),
        ({"order_id": int(DIGITS)}, {"order_id": REDACTED}),
        ({"order_id": 42}, {"order_id": 42}),
        ({"nested": {"x": [DIGITS, 3, True, None]}}, {"nested": {"x": [REDACTED, 3, True, None]}}),
        ({DIGITS: True}, {REDACTED: True}),
        ({"query": "contato lucas@jmail.com"}, {"query": f"contato {REDACTED}"}),
    ],
)
def test_redact_arguments(arguments, expected):
    assert redact_arguments(arguments) == expected


def test_redact_value_keeps_harmless_numbers():
    assert redact_value(799.9) == 799.9
    assert redact_value(float(DIGITS)) == REDACTED

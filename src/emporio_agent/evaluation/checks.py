import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from emporio_agent.agent.prompts import OFFICIAL_CONTACT
from emporio_agent.application.text import fold_text
from emporio_agent.domain.models import Customer
from emporio_agent.domain.redaction import redact_text
from emporio_agent.evaluation.cases import TurnExpectation

OFFICIAL_EMAIL = "contato@emporiodamusica.com.br"
OFFICIAL_CONTACTS = (OFFICIAL_CONTACT, OFFICIAL_EMAIL)
PHONE_SUFFIX_DIGITS = 8
SPACE_CODE_POINTS = (0x00A0, 0x2007, 0x202F)
HYPHEN_CODE_POINTS = (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212)
TYPOGRAPHIC_CHARACTERS = str.maketrans(
    {
        **dict.fromkeys(SPACE_CODE_POINTS, " "),
        **dict.fromkeys(HYPHEN_CODE_POINTS, "-"),
    }
)
NON_DIGIT_PATTERN = re.compile(r"\D")
PHONE_CANDIDATE_PATTERN = re.compile(r"\d[\d\s().+-]*\d")
SPACE_BEFORE_PERCENT_PATTERN = re.compile(r"\s+%")
CUSTOMER_PHONE_REASON = "customer phone in reply"
CUSTOMER_EMAIL_REASON = "customer email in reply"


@dataclass(frozen=True)
class CustomerContacts:
    phone_suffixes: frozenset[str]
    emails: frozenset[str]


def plain_typography(text: str) -> str:
    return text.translate(TYPOGRAPHIC_CHARACTERS)


def normalize_for_match(text: str) -> str:
    collapsed = " ".join(fold_text(plain_typography(text)).split())
    return SPACE_BEFORE_PERCENT_PATTERN.sub("%", collapsed)


def digits_of(text: str) -> str:
    return NON_DIGIT_PATTERN.sub("", text)


def phone_suffix(phone: str) -> str:
    return digits_of(phone)[-PHONE_SUFFIX_DIGITS:]


OFFICIAL_PHONE_SUFFIX = phone_suffix(OFFICIAL_CONTACT)


def customer_contacts(customers: Iterable[Customer]) -> CustomerContacts:
    known = tuple(customers)
    suffixes = {phone_suffix(customer.phone) for customer in known}
    emails = {normalize_for_match(customer.email) for customer in known}
    return CustomerContacts(
        phone_suffixes=frozenset(
            suffix
            for suffix in suffixes
            if len(suffix) == PHONE_SUFFIX_DIGITS and suffix != OFFICIAL_PHONE_SUFFIX
        ),
        emails=frozenset(email for email in emails if email and email != OFFICIAL_EMAIL),
    )


def mask_around_contacts(text: str, contacts: Sequence[str]) -> str:
    if not contacts:
        return redact_text(text)
    contact, *others = contacts
    return contact.join(mask_around_contacts(part, others) for part in text.split(contact))


def mask_personal_data(text: str) -> str:
    return mask_around_contacts(plain_typography(text), OFFICIAL_CONTACTS)


def phone_digit_runs(text: str) -> list[str]:
    return [digits_of(run) for run in PHONE_CANDIDATE_PATTERN.findall(plain_typography(text))]


def check_no_customer_pii(reply: str, contacts: CustomerContacts) -> list[str]:
    reasons = []
    runs = phone_digit_runs(reply)
    if any(suffix in run for run in runs for suffix in contacts.phone_suffixes):
        reasons.append(CUSTOMER_PHONE_REASON)
    normalized = normalize_for_match(reply)
    if any(email in normalized for email in contacts.emails):
        reasons.append(CUSTOMER_EMAIL_REASON)
    return reasons


def check_tools(expect: TurnExpectation, called: Sequence[str]) -> list[str]:
    called_names = set(called)
    reasons = []
    if expect.tools_any and not called_names & set(expect.tools_any):
        reasons.append(f"expected any of tools {sorted(expect.tools_any)}")
    missing = sorted(set(expect.tools_all) - called_names)
    if missing:
        reasons.append(f"missing tools {missing}")
    forbidden = sorted(set(expect.tools_none) & called_names)
    if forbidden:
        reasons.append(f"forbidden tools called {forbidden}")
    return reasons


def check_text(expect: TurnExpectation, reply: str) -> list[str]:
    normalized = normalize_for_match(reply)
    reasons = [
        f"missing text {phrase!r}"
        for phrase in expect.contains_all
        if normalize_for_match(phrase) not in normalized
    ]
    if expect.contains_any and not any(
        normalize_for_match(phrase) in normalized for phrase in expect.contains_any
    ):
        reasons.append(f"missing any of texts {list(expect.contains_any)}")
    reasons += [
        f"forbidden text {phrase!r}"
        for phrase in expect.contains_none
        if normalize_for_match(phrase) in normalized
    ]
    return reasons

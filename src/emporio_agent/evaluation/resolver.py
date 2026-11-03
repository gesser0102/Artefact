import re
from collections.abc import Iterable, Sequence

from emporio_agent.application.ports import OrderRepository
from emporio_agent.domain.exceptions import EvalCaseError
from emporio_agent.domain.models import Customer
from emporio_agent.evaluation.cases import EvalCase
from emporio_agent.evaluation.checks import CustomerContacts, customer_contacts

PHONE_FIELD = "phone"
FIRST_NAME_FIELD = "first_name"
PLACEHOLDER_PATTERN = re.compile(r"\{([^{}]*)\}")
PLACEHOLDER_FORM = re.compile(rf"({PHONE_FIELD}|{FIRST_NAME_FIELD}):order_([0-9]+)")


def placeholders_in(text: str) -> list[str]:
    return PLACEHOLDER_PATTERN.findall(text)


class EvalDataResolver:
    def __init__(self, orders: OrderRepository, customers: Iterable[Customer]) -> None:
        self._orders = orders
        self._contacts = customer_contacts(customers)

    @property
    def contacts(self) -> CustomerContacts:
        return self._contacts

    def resolve(self, text: str) -> str:
        return PLACEHOLDER_PATTERN.sub(lambda match: self._value_of(match.group(1)), text)

    def validate(self, cases: Sequence[EvalCase]) -> None:
        for case in cases:
            for turn in case.turns:
                self.resolve(turn.user)

    def _value_of(self, placeholder: str) -> str:
        form = PLACEHOLDER_FORM.fullmatch(placeholder)
        if form is None:
            raise EvalCaseError(f"unknown placeholder {{{placeholder}}}")
        customer = self._customer_of_order(int(form.group(2)), placeholder)
        if form.group(1) == PHONE_FIELD:
            return customer.phone
        return customer.name.split()[0]

    def _customer_of_order(self, order_id: int, placeholder: str) -> Customer:
        order = self._orders.get_order(order_id)
        customer = None if order is None else self._orders.get_customer(order.customer_id)
        if customer is None:
            raise EvalCaseError(f"placeholder {{{placeholder}}} references unknown order")
        return customer

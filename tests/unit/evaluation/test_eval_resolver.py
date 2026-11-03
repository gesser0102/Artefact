import pytest

from emporio_agent.domain.exceptions import EvalCaseError
from emporio_agent.evaluation.cases import EvalCase, EvalTurn, TurnExpectation
from emporio_agent.evaluation.resolver import EvalDataResolver, placeholders_in
from fakes import InMemoryOrderRepository, make_customer, make_order

OWNER_PHONE = "(11) 97777-1212"
OTHER_PHONE = "(21) 96666-3434"
CUSTOMERS = (
    make_customer(1, OWNER_PHONE, name="Joana Prado Teste", email="joana@example.com"),
    make_customer(2, OTHER_PHONE, name="Caio Lima", email="caio@example.com"),
)


@pytest.fixture
def resolver() -> EvalDataResolver:
    orders = InMemoryOrderRepository(orders=[make_order(7, 1)], customers=CUSTOMERS)
    return EvalDataResolver(orders, CUSTOMERS)


def eval_case(*users: str) -> EvalCase:
    return EvalCase("c", "orders", "d", tuple(EvalTurn(u, TurnExpectation()) for u in users))


def test_resolves_phone_and_first_name_of_the_order_owner(resolver):
    text = "sou {first_name:order_7}, tel {phone:order_7}, pedido 7"

    assert resolver.resolve(text) == f"sou Joana, tel {OWNER_PHONE}, pedido 7"


def test_text_without_placeholders_is_unchanged(resolver):
    assert resolver.resolve("pedido 7, sem telefone") == "pedido 7, sem telefone"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{phone:order_99}", "unknown order"),
        ("{email:order_7}", "unknown placeholder"),
        ("{phone:pedido_7}", "unknown placeholder"),
        ("{}", "unknown placeholder"),
    ],
)
def test_unknown_placeholders_raise_domain_errors(resolver, text, message):
    with pytest.raises(EvalCaseError, match=message):
        resolver.resolve(text)


def test_validate_resolves_every_turn(resolver):
    resolver.validate([eval_case("{phone:order_7}", "ok")])

    with pytest.raises(EvalCaseError):
        resolver.validate([eval_case("ok", "{phone:order_8}")])


def test_contacts_cover_every_customer(resolver):
    assert resolver.contacts.phone_suffixes == {"77771212", "66663434"}
    assert resolver.contacts.emails == {"joana@example.com", "caio@example.com"}


def test_placeholders_in_lists_brace_tokens():
    assert placeholders_in("a {phone:order_1} b {x}") == ["phone:order_1", "x"]

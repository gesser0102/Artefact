from collections.abc import Mapping
from dataclasses import dataclass

STORE_CLARIFICATIONS_BY_SECTION: Mapping[str, tuple[str, ...]] = {
    "1": (
        "O catálogo do sistema é a fonte de verdade sobre os instrumentos à venda; "
        "a quantidade citada no manual não reflete o catálogo atual.",
    ),
    "1.2": (
        "O telefone e WhatsApp oficial é (67) 3341-4444.",
        "O e-mail oficial é contato@emporiodamusica.com.br, sem acento.",
    ),
    "7": (
        "O telefone e WhatsApp oficial é (67) 3341-4444; o número (67) 3321-4500 citado "
        "nesta seção diverge dos dados oficiais da empresa.",
    ),
    "3": ("As regras de parcelamento da seção 3.1 prevalecem sobre a tabela desta seção.",),
    "3.1": (
        "Até 3x sem juros, a parcela mínima é de R$ 50,00.",
        "As regras desta seção prevalecem sobre a tabela da seção 3.",
    ),
    "4.2": (
        "Depois de 30 dias da compra, se o produto ainda estiver na garantia legal de 90 dias "
        "contados do recebimento (seção 8.1), o caso deve ser encaminhado à equipe da loja, "
        "e não direto ao fabricante.",
    ),
    "4.3": (
        "O prazo de 7 dias para troca por preferência é contado a partir do recebimento "
        "do produto.",
    ),
    "8.1": (
        "Defeitos dentro da garantia legal e depois dos 30 dias da seção 4.2 são encaminhados "
        "à equipe da loja.",
    ),
}


@dataclass(frozen=True)
class PolicySection:
    section_id: str
    title: str
    parent_id: str | None
    parent_title: str | None
    body: str

    @property
    def is_top_level(self) -> bool:
        return self.parent_id is None

    @property
    def has_body(self) -> bool:
        return bool(self.body)


def clarifications_for(section_id: str) -> tuple[str, ...]:
    return STORE_CLARIFICATIONS_BY_SECTION.get(section_id, ())

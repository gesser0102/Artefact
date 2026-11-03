import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from emporio_agent.application.text import tokenize
from emporio_agent.domain.policies import PolicySection

BM25_K1 = 1.2
BM25_B = 0.75
RELATIVE_SCORE_FLOOR = 0.35
STEM_LENGTH = 5
TITLE_WEIGHT = 2
POLICY_STOPWORDS = frozenset(
    {
        "a",
        "as",
        "o",
        "os",
        "um",
        "uma",
        "uns",
        "umas",
        "e",
        "ou",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "num",
        "numa",
        "ao",
        "aos",
        "pelo",
        "pela",
        "para",
        "pra",
        "pro",
        "com",
        "mais",
        "bom",
        "boa",
        "bons",
        "boas",
        "the",
        "qual",
        "quais",
        "como",
        "quando",
        "onde",
        "quanto",
        "quanta",
        "quantos",
        "quantas",
        "que",
        "quem",
        "se",
        "eu",
        "me",
        "voce",
        "voces",
        "vc",
        "vcs",
        "meu",
        "minha",
        "meus",
        "minhas",
        "seu",
        "sua",
        "seus",
        "suas",
        "posso",
        "pode",
        "podem",
        "tem",
        "ter",
        "loja",
        "emporio",
        "musica",
        "sobre",
        "por",
        "favor",
        "oi",
        "ola",
        "dia",
        "tarde",
        "noite",
        "obrigado",
        "obrigada",
        "brigado",
        "valeu",
        "gostaria",
        "saber",
        "queria",
        "quero",
        "fazer",
        "faco",
        "faz",
        "ajuda",
        "ajudar",
        "nome",
        "conta",
        "contar",
        "fala",
        "falar",
        "mostra",
        "mostre",
        "mostrar",
        "ignore",
        "ignora",
        "ignorar",
        "instrucao",
        "instrucoes",
        "prompt",
        "sistema",
    }
)
SECTION_ALIASES: Mapping[str, tuple[str, ...]] = {
    "1": ("história", "fundação", "fundada", "desde", "anos", "catálogo", "marcas"),
    "1.1": ("missão", "propósito", "valores", "objetivo"),
    "1.2": (
        "cnpj",
        "endereço",
        "telefone",
        "email",
        "contato",
        "whatsapp",
        "zap",
        "número",
        "razão social",
        "fica",
        "ficam",
        "localização",
    ),
    "2": (
        "abre",
        "abrem",
        "abrir",
        "aberto",
        "aberta",
        "fecha",
        "fecham",
        "fechado",
        "domingo",
        "sábado",
        "feriado",
        "expediente",
        "horário",
        "hora",
        "horas",
    ),
    "3": (
        "pix",
        "cartão",
        "crédito",
        "débito",
        "boleto",
        "pagar",
        "pagamento",
        "aceita",
        "aceitam",
        "bandeira",
    ),
    "3.1": (
        "parcelar",
        "parcela",
        "parcelado",
        "vezes",
        "juros",
        "dividir",
        "mínima",
        "metade",
    ),
    "4": ("cdc", "consumidor"),
    "4.1": (
        "devolver",
        "devolução",
        "arrependi",
        "arrependimento",
        "desistir",
        "desisti",
        "reembolso",
        "estorno",
        "dinheiro de volta",
        "tempo",
        "prazo",
    ),
    "4.2": (
        "defeito",
        "defeituoso",
        "quebrado",
        "quebrou",
        "estragado",
        "estragou",
        "problema",
        "chegou",
        "empenado",
        "empenou",
        "torto",
        "rachado",
        "rachou",
        "trincado",
        "trincou",
    ),
    "4.3": (
        "trocar",
        "cor",
        "modelo",
        "tamanho",
        "preferência",
        "outro",
        "diferente",
        "tempo",
        "prazo",
    ),
    "4.4": (
        "boquilha",
        "higiene",
        "personalizado",
        "setup",
        "regulagem",
        "encomenda",
        "venda final",
        "liquidação",
    ),
    "5.1": ("frete", "grátis", "entrega", "motoboy", "campo grande", "taxa", "chega"),
    "5.2": (
        "frete",
        "entrega",
        "prazo",
        "chega",
        "demora",
        "correios",
        "sedex",
        "pac",
        "jadlog",
        "cep",
        "cidade",
        "estado",
        "transportadora",
        "envio",
        "enviam",
        "amassada",
        "amassado",
        "avaria",
        "avariado",
        "danificada",
        "danificado",
        "transporte",
        "extravio",
        "extraviado",
        "recusar",
        "seguro",
    ),
    "5.3": ("rastreio", "rastrear", "rastreamento", "código", "acompanhar"),
    "6.1": (
        "promoção",
        "desconto",
        "black friday",
        "aniversário",
        "volta às aulas",
        "semana do músico",
        "queima",
        "oferta",
        "cupom",
    ),
    "6.2": ("cumulativo", "acumula", "acumular", "juntar", "somar", "rain check", "reserva"),
    "7": ("robô", "bot", "humano", "atendente", "pessoa"),
    "7.1": (
        "acessório",
        "corda",
        "cordas",
        "palheta",
        "cabo",
        "pedal",
        "amplificador",
        "case",
        "capa",
        "vende",
        "vendem",
        "resposta",
        "responder",
        "demora",
    ),
    "7.2": ("passo a passo", "etapas", "fluxo"),
    "7.3": (
        "reclamação",
        "reclamar",
        "esgotado",
        "indisponível",
        "estoque",
        "descontinuado",
        "expirada",
        "vencida",
    ),
    "8.1": ("garantia", "legal", "noventa"),
    "8.2": ("garantia", "fabricante", "conserto", "certificado"),
    "8.3": ("garantia", "cobre", "cobertura", "desgaste", "mau uso", "queda", "caiu"),
    "9": (
        "dados",
        "lgpd",
        "privacidade",
        "excluir",
        "apagar",
        "deletar",
        "remover",
        "cadastro",
        "pessoais",
        "consentimento",
        "receber",
        "parar",
        "propaganda",
        "marketing",
        "novidades",
        "empresas",
        "terceiros",
    ),
    "10": ("manual", "mudar", "mudança", "atualização", "gerência"),
}


@dataclass(frozen=True)
class SectionDocument:
    section: PolicySection
    term_counts: Mapping[str, int]
    length: int


def stem(token: str) -> str:
    if token.isalpha() and len(token) >= STEM_LENGTH:
        return token[:STEM_LENGTH]
    return token


def search_terms(text: str) -> list[str]:
    return [stem(token) for token in tokenize(text) if token not in POLICY_STOPWORDS]


def alias_terms(section_id: str) -> list[str]:
    return search_terms(" ".join(SECTION_ALIASES.get(section_id, ())))


def document_terms(section: PolicySection) -> list[str]:
    return [
        *search_terms(section.title) * TITLE_WEIGHT,
        *search_terms(section.parent_title or ""),
        *search_terms(section.body),
        *alias_terms(section.section_id),
    ]


def document_for(section: PolicySection) -> SectionDocument:
    terms = document_terms(section)
    return SectionDocument(section=section, term_counts=Counter(terms), length=len(terms))


def inverse_document_frequency(term: str, documents: Sequence[SectionDocument]) -> float:
    containing = sum(term in document.term_counts for document in documents)
    return math.log(1 + (len(documents) - containing + 0.5) / (containing + 0.5))


def bm25_score(
    idf_by_term: Mapping[str, float],
    document: SectionDocument,
    average_length: float,
) -> float:
    length_ratio = document.length / average_length
    score = 0.0
    for term, idf in idf_by_term.items():
        frequency = document.term_counts.get(term, 0)
        if frequency:
            saturation = frequency + BM25_K1 * (1 - BM25_B + BM25_B * length_ratio)
            score += idf * frequency * (BM25_K1 + 1) / saturation
    return score


def scored_sections(
    query_terms: Iterable[str],
    documents: Sequence[SectionDocument],
) -> list[tuple[float, int, PolicySection]]:
    average_length = sum(document.length for document in documents) / len(documents)
    idf_by_term = {term: inverse_document_frequency(term, documents) for term in query_terms}
    return [
        (bm25_score(idf_by_term, document, average_length), position, document.section)
        for position, document in enumerate(documents)
    ]


def rank_sections(
    query: str,
    sections: Sequence[PolicySection],
    limit: int,
) -> list[PolicySection]:
    documents = [document_for(section) for section in sections if section.has_body]
    query_terms = dict.fromkeys(search_terms(query))
    if not documents or not query_terms:
        return []
    scored = sorted(
        (entry for entry in scored_sections(query_terms, documents) if entry[0] > 0),
        key=lambda entry: (-entry[0], entry[1]),
    )
    if not scored:
        return []
    score_floor = RELATIVE_SCORE_FLOOR * scored[0][0]
    return [section for score, _, section in scored if score >= score_floor][:limit]

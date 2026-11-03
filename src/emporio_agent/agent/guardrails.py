from emporio_agent.agent.tools.registry import ORDER_TOOL_NAMES
from emporio_agent.agent.tools.serialization import (
    serialize_locked,
    serialize_not_verified,
    to_tool_json,
)
from emporio_agent.domain.exceptions import ChatModelFailure

MAX_FAILED_IDENTITY_ATTEMPTS = 3
MAX_USER_MESSAGE_CHARS = 2000
MAX_TOOL_STEPS_PER_TURN = 6
NOT_VERIFIED_OUTPUT = to_tool_json(serialize_not_verified())
LOCKED_OUTPUT = to_tool_json(serialize_locked())
MESSAGE_TOO_LONG_REPLY = (
    "Sua mensagem ficou um pouco longa para mim. Pode resumir em poucas linhas o que você "
    "precisa? Assim consigo te ajudar melhor."
)
EMPTY_ANSWER_REPLY = (
    "Desculpe, não consegui montar uma resposta agora. Pode repetir sua pergunta de outro jeito?"
)
RATE_LIMITED_REPLY = (
    "Estou com muitas conversas agora. Pode tentar de novo em instantes? Já já te atendo."
)
UNAVAILABLE_REPLY = (
    "Estamos com uma instabilidade no atendimento virtual. Tente de novo em alguns minutos "
    "ou fale com a nossa equipe pelo (67) 3341-4444."
)


def reply_for_failure(reason: ChatModelFailure) -> str:
    return RATE_LIMITED_REPLY if reason is ChatModelFailure.RATE_LIMITED else UNAVAILABLE_REPLY


def is_message_too_long(user_text: str) -> bool:
    return len(user_text) > MAX_USER_MESSAGE_CHARS


class IdentityAttemptGuard:
    def __init__(self) -> None:
        self._failed_attempts = 0

    @property
    def failed_attempts(self) -> int:
        return self._failed_attempts

    @property
    def is_locked(self) -> bool:
        return self._failed_attempts >= MAX_FAILED_IDENTITY_ATTEMPTS

    def blocks(self, tool_name: str) -> bool:
        return tool_name in ORDER_TOOL_NAMES and self.is_locked

    def observe(self, tool_name: str, output: str) -> None:
        if tool_name in ORDER_TOOL_NAMES and output == NOT_VERIFIED_OUTPUT:
            self._failed_attempts += 1

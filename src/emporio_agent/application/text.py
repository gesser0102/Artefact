import re
import unicodedata

TOKEN_PATTERN = re.compile(r"[a-z]+|[0-9]+")


def fold_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text).casefold()
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(fold_text(text))

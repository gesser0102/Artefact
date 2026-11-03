from emporio_agent.application.text import fold_text, tokenize


def test_tokenize_removes_accents_case_and_punctuation():
    assert tokenize("Violão ELÉTRICO, gd-20!") == ["violao", "eletrico", "gd", "20"]


def test_tokenize_splits_digits_from_letters():
    assert tokenize("12x sem juros") == ["12", "x", "sem", "juros"]


def test_fold_text_removes_accents_and_case_but_keeps_punctuation():
    assert fold_text("Seção 4.2") == "secao 4.2"

import logging
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from emporio_agent.config import Settings
from emporio_agent.domain.exceptions import DataLoadError
from emporio_agent.domain.models import OrderStatus, ProductStatus
from emporio_agent.infrastructure.observability.logging import configure_logging, log_error
from emporio_agent.infrastructure.persistence.csv_repository import CsvRepository

ORDER_IDS = range(1, 21)


@pytest.fixture
def data_copy(tmp_path: Path, data_dir: Path) -> Path:
    target = tmp_path / "data"
    target.mkdir()
    for csv_path in data_dir.glob("*.csv"):
        shutil.copy(csv_path, target / csv_path.name)
    return target


def csv_path(data_dir: Path, table: str) -> Path:
    return data_dir / f"desafio_tecnico_ai_eng - {table}.csv"


def replace_in_csv(data_dir: Path, table: str, old: str, new: str) -> None:
    path = csv_path(data_dir, table)
    content = path.read_text(encoding="utf-8")
    assert old in content
    path.write_text(content.replace(old, new, 1), encoding="utf-8")


def test_load_indexes_every_table(repository):
    assert len(repository.categories_by_id) == 9
    assert len(repository.products_by_id) == 65
    assert len(repository.promotions_by_id) == 25
    assert all(repository.get_order(order_id) for order_id in ORDER_IDS)
    assert repository.get_order(0) is None
    assert repository.get_order(21) is None
    assert sum(len(repository.list_order_items(order_id)) for order_id in ORDER_IDS) == 22
    assert repository.get_customer(1) is not None
    assert repository.get_customer(9999) is None
    assert len(repository.list_order_items(15)) == 2
    assert repository.list_order_items(9999) == ()


def test_customer_and_order_data_are_exposed_only_through_methods(repository):
    assert not hasattr(repository, "customers_by_id")
    assert not hasattr(repository, "orders_by_id")
    assert not hasattr(repository, "order_items_by_order_id")


def test_repository_repr_does_not_list_customers(repository):
    customer = repository.get_customer(1)

    assert customer.city not in repr(repository)
    assert customer.name not in repr(repository)


def test_product_fields_are_typed(repository):
    product = repository.products_by_id[81]

    assert product.price_brl == Decimal("599.9")
    assert isinstance(product.price_brl, Decimal)
    assert product.specs["electronics"] == "no"
    assert product.status is ProductStatus.ACTIVE
    assert product.created_at == date(2021, 3, 15)


def test_order_fields_are_typed_and_blanks_become_none(repository):
    delivered = repository.get_order(4)
    pending = repository.get_order(13)

    assert delivered.total_brl == Decimal("799.9")
    assert isinstance(delivered.total_brl, Decimal)
    assert delivered.status is OrderStatus.DELIVERED
    assert pending.status is OrderStatus.PENDING
    assert delivered.estimated_delivery == date(2025, 12, 22)
    assert pending.tracking_code is None
    assert pending.estimated_delivery is None
    assert pending.notes is None


def test_only_flagged_promotions_are_indexed_as_active(repository):
    assert sorted(repository.active_promotions_by_product_id) == [90, 94, 121, 127]
    assert not repository.promotions_by_id[4].is_active


def test_customer_repr_hides_contact_data(repository):
    customer = repository.get_customer(1)

    assert customer.phone not in repr(customer)
    assert customer.email not in repr(customer)


def test_missing_directory_raises_data_load_error(tmp_path, caplog):
    with pytest.raises(DataLoadError):
        CsvRepository.load(tmp_path / "missing")

    assert "csv_repository.read_rows" in caplog.text
    assert "store." not in caplog.text


def test_row_parsing_failure_logs_current_scope(data_copy, caplog):
    replace_in_csv(data_copy, "products", "81,599.9,", "81,abc,")

    with pytest.raises(DataLoadError):
        CsvRepository.load(data_copy)

    assert "csv_repository.load_table" in caplog.text
    assert "store." not in caplog.text


def test_inconsistent_data_logs_current_scope(data_copy, caplog):
    replace_in_csv(data_copy, "promotions", "1,102,10", "1,9999,10")

    with pytest.raises(DataLoadError):
        CsvRepository.load(data_copy)

    assert "csv_repository.load " in caplog.text
    assert "store." not in caplog.text


def test_unknown_order_status_raises_data_load_error(data_copy):
    replace_in_csv(data_copy, "orders", ",delivered,", ",lost,")

    with pytest.raises(DataLoadError):
        CsvRepository.load(data_copy)


def test_malformed_price_raises_data_load_error(data_copy):
    replace_in_csv(data_copy, "products", "81,599.9,", "81,abc,")

    with pytest.raises(DataLoadError):
        CsvRepository.load(data_copy)


def test_malformed_specs_raises_data_load_error(data_copy):
    replace_in_csv(
        data_copy, "products", '"{""top"":""Spruce"",""back_sides"":""Meranti""', '"{broken'
    )

    with pytest.raises(DataLoadError):
        CsvRepository.load(data_copy)


def test_unknown_product_status_raises_data_load_error(data_copy):
    replace_in_csv(data_copy, "products", ",discontinued,", ",retired,")

    with pytest.raises(DataLoadError):
        CsvRepository.load(data_copy)


def test_empty_table_raises_data_load_error(data_copy):
    csv_path(data_copy, "categories").write_text("category_id,name,description\n", encoding="utf-8")

    with pytest.raises(DataLoadError):
        CsvRepository.load(data_copy)


def test_two_active_promotions_for_one_product_raise_data_load_error(data_copy):
    replace_in_csv(
        data_copy, "promotions", "22,96,40,Semana do Músico,0", "22,127,40,Semana do Músico,1"
    )

    with pytest.raises(DataLoadError):
        CsvRepository.load(data_copy)


def test_dangling_reference_raises_data_load_error(data_copy):
    replace_in_csv(data_copy, "promotions", "1,102,10", "1,9999,10")

    with pytest.raises(DataLoadError):
        CsvRepository.load(data_copy)


def test_load_failure_does_not_log_customer_contact_data(data_copy, caplog, monkeypatch):
    monkeypatch.setenv("EMPORIO_DEBUG", "1")
    configure_logging(Settings(_env_file=None).debug)
    replace_in_csv(data_copy, "customers", "1,Lucas", "(67) 99812-3456,Lucas")

    with pytest.raises(DataLoadError) as raised:
        CsvRepository.load(data_copy)

    assert "99812" not in caplog.text
    assert "99812" not in str(raised.value)


def test_log_error_redacts_sensitive_values_and_keys(caplog):
    log_error(
        "scope",
        ValueError("contato lucas.mendes@jmail.com (67) 99812-3456 gsk_abc123"),
        phone="anything",
        api_key="anything-else",
        note="fone 67998123456",
        order_id=7,
    )

    assert "lucas.mendes" not in caplog.text
    assert "99812" not in caplog.text
    assert "gsk_abc123" not in caplog.text
    assert "anything" not in caplog.text
    assert "67998123456" not in caplog.text
    assert "'order_id': '7'" in caplog.text


@pytest.mark.parametrize(
    "phone",
    [
        "(11) 91234-5678",
        "11912345678",
        "11 91234-5678",
        "55 11 91234-5678",
        "+55 11 91234-5678",
        "5511912345678",
        "+5511912345678",
    ],
)
def test_log_error_redacts_every_accepted_phone_format(caplog, phone):
    log_error("scope", ValueError(f"contato {phone} fim"))

    assert phone not in caplog.text
    assert "91234" not in caplog.text
    assert "contato [redacted] fim" in caplog.text


def test_emporio_debug_controls_traceback_logging(caplog, monkeypatch):
    monkeypatch.delenv("EMPORIO_DEBUG", raising=False)
    configure_logging(Settings(_env_file=None).debug)
    log_error("scope", ValueError("quiet"))
    assert not [record for record in caplog.records if record.levelno == logging.DEBUG]

    caplog.clear()
    monkeypatch.setenv("EMPORIO_DEBUG", "1")
    configure_logging(Settings(_env_file=None).debug)
    log_error("scope", ValueError("verbose"))
    assert [record for record in caplog.records if record.levelno == logging.DEBUG]

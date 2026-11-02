import logging
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from emporio_agent.config import Settings
from emporio_agent.domain.exceptions import DataLoadError
from emporio_agent.domain.models import ProductStatus
from emporio_agent.infrastructure.observability.logging import configure_logging, log_error
from emporio_agent.infrastructure.persistence.csv_repository import CsvCatalogRepository


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
    assert len(repository.orders_by_id) == 20
    assert sum(len(items) for items in repository.order_items_by_order_id.values()) == 22
    assert repository.customers_by_id
    assert len(repository.order_items_by_order_id[15]) == 2


def test_product_fields_are_typed(repository):
    product = repository.products_by_id[81]

    assert product.price_brl == Decimal("599.9")
    assert isinstance(product.price_brl, Decimal)
    assert product.specs["electronics"] == "no"
    assert product.status is ProductStatus.ACTIVE
    assert product.created_at == date(2021, 3, 15)


def test_order_fields_are_typed_and_blanks_become_none(repository):
    delivered = repository.orders_by_id[4]
    pending = repository.orders_by_id[13]

    assert delivered.total_brl == Decimal("799.9")
    assert isinstance(delivered.total_brl, Decimal)
    assert delivered.estimated_delivery == date(2025, 12, 22)
    assert pending.tracking_code is None
    assert pending.estimated_delivery is None
    assert pending.notes is None


def test_only_flagged_promotions_are_indexed_as_active(repository):
    assert sorted(repository.active_promotions_by_product_id) == [90, 94, 121, 127]
    assert not repository.promotions_by_id[4].is_active


def test_customer_repr_hides_contact_data(repository):
    customer = repository.customers_by_id[1]

    assert customer.phone not in repr(customer)
    assert customer.email not in repr(customer)


def test_missing_directory_raises_data_load_error(tmp_path, caplog):
    with pytest.raises(DataLoadError):
        CsvCatalogRepository.load(tmp_path / "missing")

    assert "store.read_rows" in caplog.text


def test_malformed_price_raises_data_load_error(data_copy):
    replace_in_csv(data_copy, "products", "81,599.9,", "81,abc,")

    with pytest.raises(DataLoadError):
        CsvCatalogRepository.load(data_copy)


def test_malformed_specs_raises_data_load_error(data_copy):
    replace_in_csv(
        data_copy, "products", '"{""top"":""Spruce"",""back_sides"":""Meranti""', '"{broken'
    )

    with pytest.raises(DataLoadError):
        CsvCatalogRepository.load(data_copy)


def test_unknown_product_status_raises_data_load_error(data_copy):
    replace_in_csv(data_copy, "products", ",discontinued,", ",retired,")

    with pytest.raises(DataLoadError):
        CsvCatalogRepository.load(data_copy)


def test_empty_table_raises_data_load_error(data_copy):
    csv_path(data_copy, "categories").write_text("category_id,name,description\n", encoding="utf-8")

    with pytest.raises(DataLoadError):
        CsvCatalogRepository.load(data_copy)


def test_two_active_promotions_for_one_product_raise_data_load_error(data_copy):
    replace_in_csv(
        data_copy, "promotions", "22,96,40,Semana do Músico,0", "22,127,40,Semana do Músico,1"
    )

    with pytest.raises(DataLoadError):
        CsvCatalogRepository.load(data_copy)


def test_dangling_reference_raises_data_load_error(data_copy):
    replace_in_csv(data_copy, "promotions", "1,102,10", "1,9999,10")

    with pytest.raises(DataLoadError):
        CsvCatalogRepository.load(data_copy)


def test_load_failure_does_not_log_customer_contact_data(data_copy, caplog, monkeypatch):
    monkeypatch.setenv("EMPORIO_DEBUG", "1")
    configure_logging(Settings().debug)
    replace_in_csv(data_copy, "customers", "1,Lucas", "(67) 99812-3456,Lucas")

    with pytest.raises(DataLoadError) as raised:
        CsvCatalogRepository.load(data_copy)

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


def test_emporio_debug_controls_traceback_logging(caplog, monkeypatch):
    monkeypatch.delenv("EMPORIO_DEBUG", raising=False)
    configure_logging(Settings().debug)
    log_error("scope", ValueError("quiet"))
    assert not [record for record in caplog.records if record.levelno == logging.DEBUG]

    caplog.clear()
    monkeypatch.setenv("EMPORIO_DEBUG", "1")
    configure_logging(Settings().debug)
    log_error("scope", ValueError("verbose"))
    assert [record for record in caplog.records if record.levelno == logging.DEBUG]

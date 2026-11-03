from collections.abc import Iterable
from decimal import Decimal

from emporio_agent.application.catalog.dtos import (
    ActivePromotion,
    AmbiguousProduct,
    CategoryOverview,
    ProductDetails,
    ProductLookup,
    ProductSummary,
    SearchResult,
)
from emporio_agent.application.catalog.query_parser import (
    asks_for_accessory,
    category_ids_for,
    contains_all_tokens,
    parse_query,
    with_synonyms,
    without_stopwords,
)
from emporio_agent.application.ports import CatalogRepository
from emporio_agent.application.text import tokenize
from emporio_agent.domain.availability import Availability, availability_of
from emporio_agent.domain.models import Product
from emporio_agent.domain.pricing import PriceQuote, quote_price

DEFAULT_SEARCH_LIMIT = 8
MAX_ALTERNATIVES = 3
UNRELIABLE_DETAIL_PRODUCT_IDS = frozenset(range(135, 145))


def has_electronics(product: Product, electronics: bool) -> bool:
    return product.specs.get("electronics") == ("yes" if electronics else "no")


class CatalogService:
    def __init__(self, repository: CatalogRepository) -> None:
        self._repository = repository

    def search_products(
        self,
        query: str | None = None,
        category: int | str | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        electronics: bool | None = None,
        include_unavailable: bool = False,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> SearchResult:
        requested_category_ids = self._resolve_category_filter(category)
        parsed_query = parse_query(query)
        has_accessory_term = (
            requested_category_ids is None
            and not parsed_query.category_ids
            and asks_for_accessory(parsed_query.text_tokens)
        )

        products = [] if has_accessory_term else list(self._repository.list_products())
        if not include_unavailable:
            products = [
                product
                for product in products
                if availability_of(product) is Availability.AVAILABLE
            ]
        if requested_category_ids is not None:
            products = [p for p in products if p.category_id in requested_category_ids]
        if parsed_query.category_ids:
            products = [p for p in products if p.category_id in parsed_query.category_ids]
        if electronics is not None:
            products = [p for p in products if has_electronics(p, electronics)]
        if parsed_query.text_tokens:
            products = [
                p
                for p in products
                if contains_all_tokens(parsed_query.text_tokens, self._searchable_words(p))
            ]
        if min_price is not None:
            products = [p for p in products if self._final_price_of(p) >= min_price]
        if max_price is not None:
            products = [p for p in products if self._final_price_of(p) <= max_price]

        ordered_products = self._sorted_by_final_price(products)
        return SearchResult(
            total_matches=len(ordered_products),
            items=tuple(self._summary_of(p) for p in ordered_products[: max(limit, 0)]),
        )

    def get_product(
        self,
        product_id: int | None = None,
        name: str | None = None,
    ) -> ProductLookup:
        if product_id is not None:
            product = self._repository.get_product(product_id)
            products = [] if product is None else [product]
        else:
            products = self._find_products_by_name(name or "")
        if not products:
            return None
        if len(products) == 1:
            return self._details_of(products[0])
        ordered_products = self._sorted_by_final_price(products)
        return AmbiguousProduct(
            total_matches=len(ordered_products),
            matches=tuple(self._summary_of(p) for p in ordered_products[:DEFAULT_SEARCH_LIMIT]),
        )

    def list_categories(self) -> tuple[CategoryOverview, ...]:
        available_products = [
            product
            for product in self._repository.list_products()
            if availability_of(product) is Availability.AVAILABLE
        ]
        return tuple(
            CategoryOverview(
                category_id=category.category_id,
                name=category.name,
                available_products=sum(
                    product.category_id == category.category_id for product in available_products
                ),
            )
            for category in self._repository.list_categories()
        )

    def list_active_promotions(self) -> tuple[ActivePromotion, ...]:
        promotions = []
        for promotion in self._repository.list_active_promotions():
            product = self._repository.get_product(promotion.product_id)
            if product is None:
                raise LookupError(f"promotion references missing id {promotion.product_id}")
            promotions.append(
                ActivePromotion(
                    promotion_id=promotion.promotion_id,
                    product_id=product.product_id,
                    name=product.name,
                    description=promotion.description,
                    quote=self._quote_for(product),
                    availability=availability_of(product),
                )
            )
        return tuple(promotions)

    def _resolve_category_filter(self, category: int | str | None) -> frozenset[int] | None:
        if category is None:
            return None
        if isinstance(category, int):
            return frozenset({category})
        tokens = tokenize(category)
        exact_ids = frozenset(
            known_category.category_id
            for known_category in self._repository.list_categories()
            if tokenize(known_category.name) == tokens
        )
        return exact_ids or category_ids_for(tokens)

    def _quote_for(self, product: Product) -> PriceQuote:
        promotion = self._repository.get_active_promotion(product.product_id)
        return quote_price(product.price_brl, promotion.discount_percent if promotion else None)

    def _final_price_of(self, product: Product) -> Decimal:
        return self._quote_for(product).final_price

    def _sorted_by_final_price(self, products: Iterable[Product]) -> list[Product]:
        return sorted(
            products,
            key=lambda product: (self._final_price_of(product), product.product_id),
        )

    def _summary_of(self, product: Product) -> ProductSummary:
        return ProductSummary(
            product_id=product.product_id,
            name=product.name,
            category=self._repository.get_category(product.category_id).name,
            quote=self._quote_for(product),
            availability=availability_of(product),
            stock_quantity=product.stock_quantity,
        )

    def _searchable_words(self, product: Product) -> set[str]:
        category_name = self._repository.get_category(product.category_id).name
        searchable_text = f"{product.name} {category_name}"
        if product.product_id not in UNRELIABLE_DETAIL_PRODUCT_IDS:
            searchable_text = f"{searchable_text} {product.description}"
        return with_synonyms(set(tokenize(searchable_text)))

    def _find_products_by_name(self, name: str) -> list[Product]:
        products = self._repository.list_products()
        target_tokens = tokenize(name)
        exact_matches = [p for p in products if tokenize(p.name) == target_tokens]
        name_tokens = without_stopwords(target_tokens)
        if exact_matches or not name_tokens:
            return exact_matches
        return [p for p in products if contains_all_tokens(name_tokens, set(tokenize(p.name)))]

    def _find_alternatives(self, product: Product) -> tuple[ProductSummary, ...]:
        reference_price = self._final_price_of(product)
        candidates = [
            candidate
            for candidate in self._repository.list_products()
            if candidate.category_id == product.category_id
            and availability_of(candidate) is Availability.AVAILABLE
        ]
        closest = sorted(
            candidates,
            key=lambda candidate: (
                abs(self._final_price_of(candidate) - reference_price),
                candidate.product_id,
            ),
        )
        return tuple(self._summary_of(candidate) for candidate in closest[:MAX_ALTERNATIVES])

    def _details_of(self, product: Product) -> ProductDetails:
        details_reliable = product.product_id not in UNRELIABLE_DETAIL_PRODUCT_IDS
        is_available = availability_of(product) is Availability.AVAILABLE
        return ProductDetails(
            summary=self._summary_of(product),
            details_reliable=details_reliable,
            description=product.description if details_reliable else None,
            specs=dict(product.specs) if details_reliable else None,
            alternatives=None if is_available else self._find_alternatives(product),
        )

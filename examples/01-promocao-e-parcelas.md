# Conversa com a Lia — Empório da Música

_Cenário `catalog_active_promotion` da avaliação de 04/11/2026, modelo `openai/gpt-oss-120b`. A Lia encadeia duas ferramentas na mesma resposta: acha o produto e cota as parcelas sobre o preço promocional._

**Cliente:** oii o ukulele ohana ck-20 ta com algum desconto?

**Lia:** Oi! Temos o **Ohana CK-20 Concert Natural** com **20 % de desconto** - de R$ 549,00 por **R$ 439,20**. Está em estoque (6 unidades).

💳 Parcelamento sem juros: até 5x de R$ 87,84 (ou à vista por R$ 439,20).

Quer confirmar a compra ou saber mais? 🚀

<details><summary>Ferramentas: search_products, quote_installments · tokens 5885+195 · retries 0</summary>

- `search_products` `{"include_unavailable": false, "limit": 5, "query": "ukulele ohana ck-20"}` (ok)
- `quote_installments` `{"amount": 439.2}` (ok)

</details>

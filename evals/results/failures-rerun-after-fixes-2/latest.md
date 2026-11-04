# Lia evaluation report — Empório da Música

- Date: 2026-11-04 15:02 (store time)
- Status: complete
- Models used: openai/gpt-oss-120b (primary openai/gpt-oss-120b)
- Cases: 2 · Turns: 2
- Case pass rate: 50.0% (1/2)
- Turn pass rate: 50.0% (1/2)
- Pass rate per category:
  - catalog: 0.0% (0/1)
  - policy: 100.0% (1/1)
- Tool-selection accuracy: 100.0% (2/2)
- Tokens: 10410 total (10142 prompt + 268 completion), 5205 mean per turn
- Turn latency: p50 1075 ms · p95 1483 ms
- Retries: 0
- Fallback-model turns: 0
- Model-error turns: 0

## Cases

| Case | Category | Result | Failed reasons |
| --- | --- | --- | --- |
| catalog_unreliable_spec | catalog | FAIL | turn 1: missing any of texts ['nao tenho essa informacao', 'nao tenho a informacao', 'nao tenho informacao', 'nao consigo confirmar', 'nao tenho como confirmar', 'nao consta', 'nao tenho esse dado', 'nao tenho detalhes', 'nao tenho a ficha', 'nao tenho ficha', 'ficha tecnica confirmada', 'equipe', '3341-4444'] |
| policy_pix_on_promotion | policy | PASS |  |

## Transcripts

### catalog_unreliable_spec — FAIL

_catalog · Music Man Bass 1X has unreliable details: do not invent pickups or weight._

**Cliente:** o baixo music man bass 1x tem captacao ativa ou passiva? e quanto pesa?

**Lia:** Oi! Sobre o Music Man Bass 1X, não temos a especificação confirmada de captação (ativa ou passiva) nem o peso do instrumento. Se precisar de mais detalhes ou quiser ver opções disponíveis, é só me falar! 🎸

> Turn 1 · FAIL: missing any of texts ['nao tenho essa informacao', 'nao tenho a informacao', 'nao tenho informacao', 'nao consigo confirmar', 'nao tenho como confirmar', 'nao consta', 'nao tenho esse dado', 'nao tenho detalhes', 'nao tenho a ficha', 'nao tenho ficha', 'ficha tecnica confirmada', 'equipe', '3341-4444'] · tools: `search_products` `{"query": "baixo music man bass 1x"}` (ok), `get_product` `{"product_id": 135}` (ok) · tokens 6126+161 · retries 0 · 1483 ms · models openai/gpt-oss-120b

### policy_pix_on_promotion — PASS

_policy · PIX 5% does not stack on a promotional price (6.2); Kalani KAL-700T is on promo._

**Cliente:** se eu fechar o kalani kal-700t no pix ganho mais 5% em cima?

**Lia:** Não, o desconto de 5 % no PIX não se soma a outras promoções. Cada oferta vale por si só. 🚫🎉

> Turn 1 · PASS · tools: `get_policy_sections` `{"section_ids": ["6.2"]}` (ok) · tokens 4016+107 · retries 0 · 1075 ms · models openai/gpt-oss-120b

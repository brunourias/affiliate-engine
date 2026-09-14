# Integração Mercado Livre — V1-B.2

Documentação oficial conferida em **13/09/2026**. Base URL: `https://api.mercadolibre.com`.

Esta fase executa diagnóstico de capacidades, não ingestão de produtos. Falhas oficiais são persistidas como estado diagnóstico e nunca derrubam o Affiliate Engine. Não existe scraping nem automação de navegador.

## Endpoints oficiais

| Capability | Método e endpoint | Autenticação |
|---|---|---|
| SITE | `GET /sites/{site_id}` | testada em modo anônimo |
| CATEGORIES | `GET /sites/{site_id}/categories` | testada em modo anônimo |
| TRENDS_GLOBAL | `GET /trends/{site_id}` | testada em modo anônimo |
| TRENDS_CATEGORY | `GET /trends/{site_id}/{category_id}` | testada em modo anônimo |
| HIGHLIGHTS_CATEGORY | `GET /highlights/{site_id}/category/{category_id}` | access token segundo a documentação atual |
| MARKETPLACE_SEARCH | `GET /sites/{site_id}/search?q=...` | testada em modo anônimo; opcional |
| AUTH_USER | `GET /users/me` | access token |
| ITEM_DETAILS | `GET /items/{item_id}` | testada conforme disponibilidade oficial |
| PRICE_DETAILS | `GET /items/{item_id}/sale_price` | access token nesta implementação diagnóstica |
| REVIEWS | `GET /reviews/item/{item_id}` | access token segundo a documentação atual |
| SELLER_DETAILS | `GET /users/{seller_id}` | testada conforme disponibilidade oficial |
| CATALOG_PRODUCT | `GET /products/{catalog_product_id}` | testada conforme disponibilidade oficial |
| USER_PRODUCT | `GET /user-products/{user_product_id}` | access token |

Referências oficiais: [Tendências](https://developers.mercadolivre.com.br/devcenter/tendencias), [Mais vendidos](https://developers.mercadolivre.com.br/pt_br/mais-vendidos-no-mercado-livre), [Opiniões de produtos](https://developers.mercadolivre.com.br/pt_br/opinioes-sobre-um-produto) e [User Products](https://developers.mercadolivre.com.br/pt_br/user-products).

## Classificação

Estados: `UNKNOWN`, `AVAILABLE`, `FORBIDDEN`, `UNAUTHORIZED`, `DEGRADED`, `NOT_SUPPORTED`, `NOT_CONFIGURED` e `NOT_APPLICABLE`. HTTP 401, 403 e 429 são classificados explicitamente; timeout, rede, 5xx e JSON inválido resultam em `DEGRADED`. `Retry-After` é registrado quando presente, sem retry automático.

Busca geral é opcional porque categorias e fontes oficiais como trends/highlights podem sustentar a descoberta futura. Um 403 em `MARKETPLACE_SEARCH` não torna a conexão indisponível.

## Item, Product e User Product

Item é a publicação (`item_id`). Produto de catálogo só é consultado quando o item fornece `catalog_product_id`. User Product só é consultado quando o item fornece `user_product_id`. Ausência desses identificadores resulta em `NOT_APPLICABLE`; nenhuma relação é fabricada.

URLs informadas pelo Operator são apenas analisadas localmente para extrair um ID `MLB...`. A página não é acessada.

## Ambiente e segurança

- `MELI_SITE_ID=MLB`
- `MELI_CLIENT_ID=`
- `MELI_CLIENT_SECRET=`
- `MELI_ACCESS_TOKEN=`

Sem token, o modo é `ANONYMOUS`; com token no processo, `ENV_ACCESS_TOKEN`. Access token, refresh token, client secret e Authorization nunca são gravados no SQLite, logs, respostas, notificações ou Registro de decisões.

## Homologação real — 13/09/2026

Com aplicação oficial, permissões e OAuth reais, responderam `AVAILABLE / HTTP 200`: `AUTH_USER`, `SITE`, `CATEGORIES`, `TRENDS_GLOBAL`, `TRENDS_CATEGORY` e `HIGHLIGHTS_CATEGORY`.

Responderam `FORBIDDEN / HTTP 403`: `MARKETPLACE_SEARCH` e `ITEM_DETAILS`. O 403 de item também foi reproduzido diretamente contra a API oficial, fora do Affiliate Engine. Busca geral e detalhes de item são opcionais: o Radar usa categories e ao menos uma fonte disponível entre trends/highlights, não chama busca geral e não chama `/items/{id}`. Detalhes, preço, avaliações e vendedor não são fabricados.

## Radar

- `GET /trends/MLB` gera sinais `QUERY / TREND_GLOBAL`.
- `GET /trends/MLB/{CATEGORY_ID}` gera sinais `QUERY / TREND_CATEGORY`.
- `GET /highlights/MLB/category/{CATEGORY_ID}` preserva `ITEM`, `PRODUCT`, `USER_PRODUCT` ou `UNKNOWN`.

Cada sinal registra capability, fonte, timestamp, categoria, rank, identificador/texto e payload público mínimo. Rank oficial não é score. Não há scraping, busca alternativa, preço ou enriquecimento automático.

## Troubleshooting

### Variáveis do processo podem sobrescrever o `.env`

Uma variável `MELI_ACCESS_TOKEN` já definida no processo do PowerShell tem precedência sobre o arquivo `.env`. Para diagnosticar, verifique somente se a variável existe e reinicie o terminal/backend após corrigir o ambiente. Não imprima seu conteúdo, não copie o token para logs e não o envie ao frontend. O painel informa apenas `Anônimo` ou `Token do ambiente`.

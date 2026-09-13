# Modelo de dados

## Implementado na V1-A

- `app_settings`: singleton com meta em centavos, limite diário, timezone e toggles.
- `approvals`: solicitações `CAMPAIGN`, `FINANCIAL` ou `STRATEGIC`; estado pendente/aprovado/rejeitado e justificativa.
- `notifications`: central interna com severidade, leitura e metadata estruturada.
- `agent_tasks`: fila demonstrativa, origem automática/manual, payload, resultado, erro e timestamps.
- `decision_logs`: registro append-only de ator, entidade, ação, razão, confiança e metadata.

Entidades de domínio usam UUID; o singleton técnico de configuração usa id inteiro fixo. Dinheiro usa integer cents. Timestamps são UTC. Índices existem apenas para consultas atuais por status/data, leitura/data e ator/entidade.

## Implementado na V1-B.1

- `marketplace_connections`: estado agregado, site, modo de autenticação e identidade externa não sensível.
- `marketplace_capabilities`: um registro por provider/capability, com classificação, endpoint, HTTP status, latência e diagnóstico não sensível.

Tokens, client secret e headers de autorização não fazem parte do modelo.

## Planejado — não materializado

V1-B.2 poderá introduzir produtos, sellers, ofertas, snapshots, histórico de preço e proveniência após validação das capacidades. Fases posteriores poderão introduzir evidências, Trust Gate, Recommendation Score, Opportunity Score, Price Verdict, campanhas, criativos, publicações, conversões e memórias de aprendizado.

Ainda não existem tabelas de produtos, reviews, campanhas, scores, publicações, conversões, comunidade, wishlist ou social accounts. O único provider materializado nesta fase guarda conexão e diagnóstico, não dados comerciais.

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

## Implementado na V1-B.2

- `marketplace_categories`: categorias oficiais por provider e ID externo, com first/last seen e sem exclusão implícita.
- `radar_runs`: execução manual, fontes solicitadas/bem-sucedidas/falhas, estado e contagem.
- `radar_signals`: observações imutáveis por run com fonte, capability, categoria, rank, tipo externo e payload público mínimo.

Cada run é um snapshot temporal. Sinais não são deduplicados entre runs. `QUERY`, `ITEM`, `PRODUCT`, `USER_PRODUCT` e `UNKNOWN` não são convertidos entre si.

## Implementado na V1-C.1

- `curator_candidates`: intake manual ou originado de um RadarSignal, identidade externa preservada, estado editorial decidido pelo Operator e status/nível de evidência derivados.
- `curator_evidence`: evidências tipadas com valor, proveniência, confiança, verificação, observação e validade. Dinheiro usa centavos inteiros; evidência expirada permanece no histórico.

Checklist não é persistido. Não existem campos de Recommendation Score, Opportunity Score ou Price Verdict.

## Implementado na V1-C.2

- `curator_assessments`: snapshots imutáveis e versionados por candidato com Trust Gate, scores/coberturas, pilares, IDs de evidências, unknowns, preço e veredito editorial. `previous_assessment_id` preserva a cadeia; dinheiro continua em centavos.

## Planejado — não materializado

Fases futuras poderão introduzir produtos enriquecidos, sellers, ofertas e histórico de preço somente após fontes oficiais disponíveis. Mídia renderizada, publicações, conversões, comunidade, wishlist, social accounts e memórias de aprendizado continuam não materializadas.
## V1-D Campaign Engine

`campaigns` referencia obrigatoriamente `candidate_id` e o `assessment_id` imutável usado na criação. Snapshots editoriais, warnings, disclosures e claims proibidos não são recalculados quando um assessment posterior surge. `campaign_channels`, `campaign_angles` e `campaign_experiments` modelam planejamento multicanal e a família de hipóteses (máximo inicial de 12 experimentos).

## V1-E Creative Studio

- `creatives`: referência obrigatória à campanha e opcional ao experimento; snapshots editoriais, estratégia textual, disclosure, warnings, claims proibidos, variante e estado de revisão.
- `creative_scenes`: plano ordenado e editável de cenas, speakers BRUNO/CAROL/NARRATOR/NONE, instruções textuais e cobertura explícita de warnings. Não armazena mídia final.

Timestamps são armazenados como instantes UTC e expostos pela API com timezone explícito. A interface converte a apresentação para `America/Sao_Paulo`, sem alterar o valor persistido.
# V1-F.1a media entities

- `media_assets`: local image metadata, logical ownership, active state and a controlled relative path. Binary data stays under `data/media/assets`.
- `media_jobs`: queued render intent linked to an approved Creative, with profile, technical defaults, progress and future validation/output fields. F.1a does not execute jobs.

F.1b uses the existing job fields for state, monotonic progress, current scene, logical validation and safe human-facing failures. `SceneRenderSpec` is derived in memory and is not a table. Cancellation is represented by the persisted terminal `CANCELED` status, so no schema change was required.

SQLite backup does not back up media files. Database and `data/media` require separate backup procedures.

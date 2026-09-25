# Roadmap

## Estado atual

1. **V1-A — Foundation + Control Center**: homologada e preservada pela tag `v0.1.0`.
2. **V1-B — Connection, Capability Diagnostics, Radar e Data Foundation**: homologada; V1-B.1 foi homologada em 13/09/2026 e V1-B.2 também está homologada.
3. **V1-C — Curator Intake, Evidence, Scoring e Editorial Decision Engine**: homologada nas fases V1-C.1 e V1-C.2.
4. **V1-D — Campaign Engine**: homologada.
5. **V1-E — Creative Studio**: homologada.
6. **V1-F.1 — Local Media Engine**: homologada.
7. **V1-F.2a — Chatterbox Voice Engine**: homologada.
8. **V1-F.2b — Brand Assets & Avatars**: em desenvolvimento, conforme o estado real descrito abaixo.
9. **V1-G.1 — Instagram Static Direct Publishing**: homologada de ponta a ponta em 25/09/2026.
10. **V1-G.2 — Instagram Publication Operations / Operator UX**: próxima fase.
11. **V1-H — Analytics / Learning Loop**: futura; métricas e aprendizado vinculados a produto e campanha.
12. **V1-I — Learning Engine inicial + Agent Chat**: futura; interface apoiada em dados reais.
13. **V1-J — External Intelligence**: futura; cases e tendências externas.
14. **V2 — Owned Audience + Optimization**.
15. **V3 — Autonomous Growth**.

## V1-F — Local Media Engine

O Local Media Engine é local-first e não exige API paga para suas funções essenciais.

### V1-F.1 — homologada

- F.1a — Foundation / Diagnostics / Assets
- F.1b — Media Job Pipeline
- F.1c — Real Local Render
- F.1d — UI / Homologation

### V1-F.2a — Chatterbox Voice Engine — homologada

Provider local isolado, selecionável e compatível com Piper, com batch por `MediaJob`, normalização determinística, perfis de voz, reference audio opcional, diagnóstico, timeouts próprios, trim conservador e duração validada por FFprobe.

Known issue não bloqueante: ainda pode ocorrer pequeno descasamento entre fala e legenda no final do vídeo. O refinamento permanece futuro e não deve introduzir ASR/Whisper nesta fase.

### V1-F.2b — Brand Assets & Avatars — em desenvolvimento

Classificação local de avatares Bruno/Carol por estado visual, resolução determinística e composição segura em 9:16 estão presentes no repositório. A evolução desta fase deve continuar respeitando o estado efetivamente implementado; geração de personagens e lip-sync não fazem parte do escopo homologado.

V1-F.3 (Multi-format + Batch) permanece futura.

## V1-G — Social Publishers

### V1-G.1 — Instagram Static Direct Publishing — HOMOLOGADA

Homologação real concluída em **25/09/2026** com a conta Instagram `receitafacildapops`, profissional do tipo canônico `CREATOR`, readiness `READY`, publicação controlada de `STATIC_CARD`, retorno de `platformMediaId`, persistência da execução como `PUBLISHED` e confirmação visual do post no Instagram. Após a homologação, `publishingEnabled` foi novamente desabilitado.

Entregas:

- OAuth real para Instagram;
- `SecureTokenStore` com armazenamento seguro do access token;
- suporte a conta profissional Business/Creator;
- seleção explícita de canal;
- perfil estático para Instagram Feed;
- `PublicationExecution` persistida;
- idempotência persistente e aquisição atômica da execução;
- Media Delivery por URL HTTPS pública temporária;
- publicação real, controlada e iniciada pelo operador;
- auditoria em `DecisionLog`, sem credenciais;
- homologação real de ponta a ponta.

Fora do escopo da V1-G.1:

- Reels e vídeo;
- carrossel;
- scheduler de publicação;
- publicação automática;
- publicação em TikTok, Facebook ou YouTube.

### V1-G.2 — Instagram Publication Operations / Operator UX — PRÓXIMA

Objetivo: transformar a publicação Instagram já homologada em um fluxo operacional seguro dentro do próprio sistema, sem introduzir publicação automática.

Escopo previsto:

- interface de publicação no frontend;
- apresentação do estado da conexão e readiness;
- preview do Creative;
- readiness e blockers;
- disclosure e Media Delivery;
- confirmação explícita e botão **Publicar**;
- resultado da publicação;
- histórico de `PublicationExecution`;
- estados `PLANNED`, `PUBLISHING`, `PUBLISHED` e `FAILED`;
- `platformMediaId`, `publishedAt` e erro sanitizado;
- proteção contra duplo clique e publicação duplicada;
- possibilidade de manter `publishingEnabled` desabilitado por padrão;
- UX clara para Kill Switch e publicação;
- visualização da auditoria e do `DecisionLog` relacionado.

Fora do escopo da V1-G.2:

- Reels;
- carrossel;
- agendamento;
- publicação automática;
- retry automático;
- múltiplas redes.

A expansão de formatos permanece para uma fase posterior da V1-G.

## V2-A — YouTube Faceless / Dark Engine (futuro)

Expansão platform-agnostic após estabilidade do núcleo: produto aprovado → ideia → roteiro → narração → vídeo → thumbnail → metadados → revisão/aprovação → publicação → métricas → aprendizado. Deve suportar Shorts, vídeos longos e canais sem aparição humana, preservando curadoria, aprovação inicial, Kill Switch, controle de gastos e métricas de retenção, views, CTR, cliques, conversão e comissão.

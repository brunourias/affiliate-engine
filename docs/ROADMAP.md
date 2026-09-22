# Roadmap

1. **V1-A — Foundation + Control Center**: homologada e preservada pela tag `v0.1.0`.
2. **V1-B.1 — Connection + Capability Diagnostics**: homologada em 13/09/2026.
3. **V1-B.2 — Mercado Livre Radar + Data Foundation**: homologada.
4. **V1-C.1 — Curator Intake + Evidence Foundation**: homologada.
5. **V1-C.2 — Curator Scoring + Editorial Decision Engine**: homologada.
6. **V1-D — Campaign Engine**: homologada.
7. **V1-E — Creative Studio**: homologada.
8. **V1-F — Local Media Engine**: próxima; geração local-first de mídia, sem custo variável obrigatório.
9. **V1-G — Social Publishers**: conectores oficiais/assistidos.
10. **V1-H — Analytics / Learning Loop**: métricas e aprendizado vinculados a produto e campanha.
11. **V1-I — Learning Engine inicial + Agent Chat**: interface apoiada em dados reais.
12. **V1-J — External Intelligence**: cases e tendências externas.
13. **V2 — Owned Audience + Optimization**.
14. **V3 — Autonomous Growth**.

V1-E entrega estruturas textuais, cenas, variantes, compliance, readiness e aprovação humana, sem gerar mídia, publicar, acessar rede externa ou executar gastos.

## V1-F — Local Media Engine (futuro)

Arquitetura futura para geração local-first: Brand Assets, Avatar Motion Engine, Local Voice Engine, Subtitle Engine, Image/Post Generator, Video Composer, FFmpeg Renderer e Batch Renderer. Serviços pagos externos poderão ser opcionais, mas nenhuma função essencial dependerá deles. Nenhuma tabela, tela, endpoint ou módulo é implementado nesta fase.

## V2-A — YouTube Faceless / Dark Engine (futuro)

Expansão platform-agnostic após estabilidade do núcleo: produto aprovado → ideia → roteiro → narração → vídeo → thumbnail → metadados → revisão/aprovação → publicação → métricas → aprendizado. Deve suportar Shorts, vídeos longos e canais sem aparição humana, preservando curadoria, aprovação inicial, Kill Switch, controle de gastos e métricas de retenção, views, CTR, cliques, conversão e comissão.
# V1-F.1 — homologada

- F.1a — Foundation / Diagnostics / Assets
- F.1b — Media Job Pipeline
- F.1c — Real Local Render
- F.1d — UI / Homologation

## V1-F.2a — Chatterbox Voice Engine homologada

Provider local isolado, selecionável e compatível com Piper, com batch por MediaJob, normalização determinística, perfis de voz, reference audio opcional, diagnóstico, timeouts próprios, trim conservador e duração validada por FFprobe.

Known issue não bloqueante: ainda pode ocorrer pequeno descasamento entre fala e legenda no final do vídeo. O refinamento permanece futuro e não deve introduzir ASR/Whisper nesta fase.

V1-F.2b (Brand + Motion Avatars) não foi iniciada. V1-F.3 (Multi-format + Batch) permanece futura.

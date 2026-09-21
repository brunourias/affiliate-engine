# Arquitetura do Affiliate Engine

Monólito modular local-first, separado em dois processos de desenvolvimento: React/Vite no navegador e FastAPI como API REST versionada em `/api/v1`. A UI nunca acessa SQLite diretamente; regras críticas ficam no backend.

## Frontend

React, TypeScript strict, React Router e uma camada central de API. As rotas ativas incluem Radar, Curadoria, Campanhas, Criativos, Dashboard, Aprovações, Tarefas, Registro de decisões, Notificações, Configurações, Sistema e Roadmap. A interface usa pt-BR, nomes humanos e poucos códigos técnicos; UUIDs e enums em inglês permanecem internos e não são informação principal. O sistema visual é CSS próprio único e responsivo, com fluxos simples e o mínimo necessário de ações humanas.

## Backend

FastAPI, Pydantic e SQLAlchemy 2. Rotas HTTP coordenam serviços de domínio pequenos: transições de tarefas, decisões de aprovação, notificações e auditoria. Logs são JSON. CORS aceita somente origens locais configuradas.

O provider `integrations/mercado_livre` concentra cliente HTTP, classificação de erros e diagnóstico. Rotas não fazem chamadas HTTP diretamente. O provider usa timeout explícito, não faz retries agressivos e nunca persiste credenciais.

`MercadoLivreRadar` usa somente capabilities persistidas como `AVAILABLE`. Ele consulta trends e highlights diretamente, sem busca geral, detalhes de item ou enriquecimento. Cada execução preserva um snapshot temporal independente; falha de uma fonte não desfaz sinais obtidos das demais.

O módulo Curator recebe candidatos manualmente ou por ação explícita sobre um sinal. Checklist, Evidence Status, Evidence Level e stale são derivados por serviço testável; não representam qualidade nem score. Nenhuma criação de candidato acessa rede.

`CuratorAssessmentService` cria snapshots imutáveis e determinísticos. Trust Gate vem primeiro; UNKNOWN é excluído do denominador. Recommendation exige 60% de cobertura e Opportunity 40%, sem compartilhar finalidade. Avaliar não acessa rede.

Recommendation usa pesos 25/20/15/15/10/10/5. Pilares conhecidos partem de 50 e recebem ajustes explícitos por tipo, confiança e verificação. Opportunity usa Radar histórico para demanda/momento e mantém dados ausentes como UNKNOWN. Price Verdict compara `CURRENT_PRICE` e `PRICE_REFERENCE` HIGH/VERY_HIGH via Decimal: ≤85% excelente, ≤95% bom, ≤105% justo, ≤120% caro, acima evitar. PriceToBuy permanece nulo.

## Banco

SQLite por padrão em `data/affiliate_engine.db`, criado por Alembic. SQLAlchemy permanece portável. WAL melhora convivência entre leituras e escritas locais; foreign keys e busy timeout são ativados por conexão.

Além da migration diagnóstica `0002`, a migration `0003_radar_data_foundation` acrescenta categorias sincronizadas, runs e sinais. ITEM, PRODUCT, USER_PRODUCT e QUERY permanecem tipos externos distintos.

## Scheduler

Loop assíncrono único e idempotente dentro do processo FastAPI. A cada ciclo, verifica o Kill Switch e inicia no máximo uma tarefa automática pendente. Executa apenas `SYSTEM_HEARTBEAT` e falha controlada demonstrativa; não existe worker, broker nem ação externa.

## Execução local

Backend e frontend fazem bind em `127.0.0.1`. Não há autenticação porque esta versão não deve ser exposta à rede. Antes de cloud, autenticação e autorização serão obrigatórias.
## Campaign Engine (V1-D)

Campanhas são estratégias orgânicas sujeitas a aprovação humana. A API não publica, não acessa links de afiliado e não executa gastos. Links são manuais, apenas com validação sintática. A readiness é derivada de assessment elegível, disclosure, CTA, público, canal, ângulo e experimento; aprovação/rejeição reutiliza `Approval` e sincroniza o status da campanha.

## Futuros módulos de mídia e YouTube

V1-F será um Local Media Engine com princípio **LOCAL-FIRST CONTENT GENERATION**, reunindo assets de marca, avatar motion, voz local, legendas, geradores de imagem/post, composição, FFmpeg e renderização em lote. Não é implementado agora.

V2-A poderá oferecer um YouTube Faceless / Dark Engine platform-agnostic para Shorts e vídeos longos, sempre após curadoria e aprovação. Publicação, gastos e automação permanecerão sob Kill Switch e aprovação explícita; métricas alimentarão o Learning Loop. Não é implementado agora.

## Creative Studio (V1-E)

O Creative Studio transforma campanhas aprovadas e experimentos em estruturas textuais rastreáveis, cenas e variantes. Templates são determinísticos e locais. Compliance bloqueia claims proibidos e exige cobertura de warnings; disclosure e snapshots são copiados na criação. Approval `CREATIVE` congela o conteúdo em revisão e apenas o marca como pronto para futura renderização. Não há mídia, publicação, scraping, rede externa ou gasto. Automações futuras obedecerão ao Kill Switch.

O human-in-the-loop é aplicado onde risco, exceção ou decisão editorial exigem revisão, sem tornar toda etapa futura obrigatoriamente manual. A direção arquitetural é híbrida: ações seguras e sem custo poderão ser automatizadas; exceções e riscos sobem para revisão; qualquer gasto continua exigindo autorização explícita.
# V1-F.1a — Local Media Engine foundation

The media subsystem is local-first and separated from Creative. `MediaStorage` confines files to `data/media`; `media_assets` stores metadata and relative paths, while `media_jobs` records an immutable reference to an approved Creative and the selected render profile. `LocalMediaDiagnostics` checks FFmpeg, FFprobe, local TTS configuration and writable storage without downloads or network calls. Rendering, audio synthesis, subtitles and composition belong to F.1b/F.1c and are intentionally absent here.

F.1b adds a persisted state machine and injectable `VoiceRenderer`, `SceneRenderer`, `TimelineComposer` and `MediaValidator` protocols. Fake adapters exercise orchestration only when `MEDIA_PIPELINE_MODE=FAKE`; normal `LOCAL` mode rejects start until the real F.1c renderer exists. Background execution opens its own database session, and startup recovery marks interrupted active jobs as failed.

F.1c connects the same orchestration to `PiperVoiceRenderer`, `LocalSceneRenderer`, `LocalTimelineComposer` and `LocalMediaValidator`. A central FFmpeg adapter owns safe subprocess execution and FFprobe metadata. Text becomes UTF-8 SRT/ASS data, never shell commands. Scene files share resolution, frame rate, H.264/AAC and yuv420p; composition writes `final.tmp.mp4`, validates it, then atomically promotes it to the profile output directory.

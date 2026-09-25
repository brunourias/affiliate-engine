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

Loop assíncrono único e idempotente dentro do processo FastAPI. A cada ciclo, verifica o Kill Switch e inicia no máximo uma tarefa automática pendente. Não existe worker ou broker. O scheduler não dispara publicações sociais na V1-G.1; a publicação Instagram depende de ação explícita do operador.

## Execução local

Backend e frontend fazem bind em `127.0.0.1`. Não há autenticação porque esta versão não deve ser exposta à rede. Antes de cloud, autenticação e autorização serão obrigatórias.
## Campaign Engine (V1-D)

Campanhas são estratégias orgânicas sujeitas a aprovação humana. A API não publica, não acessa links de afiliado e não executa gastos. Links são manuais, apenas com validação sintática. A readiness é derivada de assessment elegível, disclosure, CTA, público, canal, ângulo e experimento; aprovação/rejeição reutiliza `Approval` e sincroniza o status da campanha.

## Local Media Engine — V1-F

O Local Media Engine segue o princípio **LOCAL-FIRST CONTENT GENERATION**. A V1-F.1 implementa storage e assets locais, diagnóstico de FFmpeg/FFprobe e voz, `MediaJob` persistido, pipeline orquestrado, renderização local, legendas, composição e validação por FFprobe. A V1-F.2a acrescenta o Chatterbox como provider de voz local isolado e selecionável, mantendo compatibilidade com Piper. Brand Assets e avatares possuem classificação e resolução determinísticas e composição segura conforme o estado da V1-F.2b.

O subsistema preserva separação entre Creative e mídia: um Creative aprovado fornece o snapshot de entrada; `MediaJob` registra processamento, progresso e resultado. Arquivos são confinados ao media root configurado, comandos FFmpeg usam argumentos estruturados e o arquivo final só é promovido depois da validação. Geração de personagens, lip-sync e V1-F.3 Multi-format + Batch permanecem fora do escopo atual.

## Futuro módulo de YouTube

V2-A poderá oferecer um YouTube Faceless / Dark Engine platform-agnostic para Shorts e vídeos longos, sempre após curadoria e aprovação. Publicação, gastos e automação permanecerão sob Kill Switch e aprovação explícita; métricas alimentarão o Learning Loop. Não é implementado agora.

## Creative Studio (V1-E)

O Creative Studio transforma campanhas aprovadas e experimentos em estruturas textuais rastreáveis, cenas e variantes. Templates são determinísticos e locais. Compliance bloqueia claims proibidos e exige cobertura de warnings; disclosure e snapshots são copiados na criação. Approval `CREATIVE` congela o conteúdo em revisão e o torna elegível para os fluxos posteriores de mídia e publicação. O Creative Studio não publica por conta própria, não executa scraping e não realiza gastos. Automações obedecem ao Kill Switch.

O human-in-the-loop é aplicado onde risco, exceção ou decisão editorial exigem revisão, sem tornar toda etapa futura obrigatoriamente manual. A direção arquitetural é híbrida: ações seguras e sem custo poderão ser automatizadas; exceções e riscos sobem para revisão; qualquer gasto continua exigindo autorização explícita.
# V1-F.1a — Local Media Engine foundation

The media subsystem is local-first and separated from Creative. `MediaStorage` confines files to `data/media`; `media_assets` stores metadata and relative paths, while `media_jobs` records an immutable reference to an approved Creative and the selected render profile. `LocalMediaDiagnostics` checks FFmpeg, FFprobe, local TTS configuration and writable storage without downloads or network calls. Rendering, audio synthesis, subtitles and composition belong to F.1b/F.1c and are intentionally absent here.

F.1b adds a persisted state machine and injectable `VoiceRenderer`, `SceneRenderer`, `TimelineComposer` and `MediaValidator` protocols. Fake adapters exercise orchestration only when `MEDIA_PIPELINE_MODE=FAKE`; normal `LOCAL` mode rejects start until the real F.1c renderer exists. Background execution opens its own database session, and startup recovery marks interrupted active jobs as failed.

F.1c connects the same orchestration to `PiperVoiceRenderer`, `LocalSceneRenderer`, `LocalTimelineComposer` and `LocalMediaValidator`. A central FFmpeg adapter owns safe subprocess execution and FFprobe metadata. Text becomes UTF-8 SRT/ASS data, never shell commands. Scene files share resolution, frame rate, H.264/AAC and yuv420p; composition writes `final.tmp.mp4`, validates it, then atomically promotes it to the profile output directory.

## Social Publishers — V1-G.1

A V1-G.1 introduz publicação direta, orgânica e controlada de `STATIC_CARD` no Instagram Feed. O backend continua sendo FastAPI e SQLite continua suportado. Não existe publicação automática nem scheduler disparando posts: cada execução exige ação explícita do operador, `confirm=true`, Creative `APPROVED`, package e Media Delivery `READY`, Kill Switch liberado e `publishingEnabled` ativo. Operacionalmente, `publishingEnabled` permanece desabilitado quando uma publicação não está sendo executada.

O fluxo homologado é:

`Creative APPROVED` → Publication Readiness → seleção explícita de canal → variante `INSTAGRAM_FEED` → Publication Package → disclosure explícito → Media Delivery → URL HTTPS pública temporária → Kill Switch → `publishingEnabled` → OAuth Instagram → publishing limit → image container → `media_publish` → `PublicationExecution PUBLISHED` → `DecisionLog`.

### Módulos e responsabilidades

- `InstagramConnectionService`: executa autenticação OAuth e gerencia o lifecycle da conexão com a conta profissional Business/Creator. O access token fica no `SecureTokenStore`, não no banco.
- `InstagramContentPublishingClient`: encapsula as chamadas HTTP oficiais do Instagram, com timeout explícito e respostas sanitizadas.
- `InstagramStaticPublisher`: coordena a execução externa de uma publicação estática já pronta; não gera assets nem resolve conteúdo editorial.
- `PublicationReadinessEngine`: decide se o Creative, o disclosure, o formato, o destino e os demais requisitos estão técnica e editorialmente prontos.
- `CreativeDistributionPlan`: descreve a seleção explícita de canal, placement e formato da distribuição.
- `ChannelAssetAdaptationEngine`: produz a variante de asset compatível com Instagram Feed sem assumir a responsabilidade de publicar.
- `MediaDeliveryEngine` / `SignedTemporaryMediaProvider`: expõe temporariamente a mídia aprovada por URL HTTPS pública para consumo da plataforma, separado do publisher.
- `PublicationExecution`: persiste estado, identidade lógica, rastreabilidade, `platformMediaId`, timestamps e falha sanitizada; também sustenta idempotência e controle de concorrência.
- `DecisionLog`: registra decisões e transições de auditoria sem credenciais, tokens, secrets, codes ou URLs temporárias assinadas.

### Segurança, idempotência e escopo

`packageFingerprint`, `accountId` e connector formam a identidade lógica de uma execução. O `execution_fingerprint` é único e a aquisição `PLANNED -> PUBLISHING` ocorre por atualização condicional atômica; somente a requisição vencedora chama a API externa. `PUBLISHED` é idempotente, enquanto `PUBLISHING` e `FAILED` não produzem retry automático. Falha remota persiste a execução como `FAILED` com erro sanitizado.

O único formato de publicação direta autorizado na V1-G.1 é `STATIC_CARD`. Reels, vídeo, carrossel, agendamento, auto publishing e publicação em outras redes permanecem fora da fase. A publicação não autoriza gastos.

`PUBLIC_MEDIA_BASE_URL` fornece a origem pública usada pelo `SignedTemporaryMediaProvider`. O Cloudflare Quick Tunnel foi utilizado somente na homologação local; não é dependência arquitetural nem solução de produção. O ngrok Free não serviu como media origin na homologação porque seu interstitial impediu o consumo direto pela Meta.

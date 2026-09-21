# Decisões arquiteturais

## ADR-001 — Monólito modular

FastAPI concentra API, scheduler e regras atuais. Evita worker, broker e abstrações de providers antes de haver um caso real.

## ADR-002 — CSS próprio único

A V1-A usa um pequeno sistema visual próprio em vez de adicionar um kit de UI. Isso mantém uma linguagem consistente e reduz dependências sem misturar sistemas.

## ADR-003 — Scheduler conservador

O scheduler processa no máximo uma tarefa automática por ciclo e consulta o Kill Switch imediatamente antes da execução. Ao reativar, não há disparo em massa.

## ADR-004 — SQLite WAL e backup seguro

WAL atende concorrência local simples. O backup usa a SQLite Backup API, portanto não depende de uma cópia insegura do arquivo aberto.

## ADR-005 — Demo opt-in

Migration cria somente configuração padrão. Seed precisa ser executado explicitamente e todos os registros demo têm marcação própria para limpeza seletiva.

## ADR-006 — Sem autenticação na V1-A

Processos fazem bind somente em loopback e CORS é explícito. Exposição em LAN/cloud é proibida sem autenticação e autorização.

## ADR-007 — Radar orientado por capabilities

O Radar opera com SITE, CATEGORIES e ao menos uma fonte entre trends/highlights. MARKETPLACE_SEARCH e ITEM_DETAILS são opcionais porque retornaram 403 na homologação oficial. Não há tentativa de contorno nem enriquecimento implícito.

## ADR-008 — Sinais preservam o tipo externo

QUERY, ITEM, PRODUCT, USER_PRODUCT e UNKNOWN são persistidos exatamente como observados. Rank oficial é proveniência, não score. Cada run é um snapshot independente e não existe preço quando nenhuma fonte oficial o fornece.

## ADR-009 — Suficiência de evidência precede scoring

Evidence sufficiency precedes scoring. Ausência de dados nunca é convertida em score negativo: permanece `MISSING`, `STALE`, `NOT_AVAILABLE`, `UNKNOWN` ou `INSUFFICIENT_EVIDENCE`. O sinal do Radar indica relevância de mercado naquele instante, não qualidade do produto. Status editorial continua decisão do Operator.

## ADR-010 — Trust Gate precede scoring

BLOCK sempre produz `NOT_RECOMMENDED`; Opportunity nunca substitui confiança editorial.

## ADR-011 — Scores independentes e cobertura explícita

Recommendation e Opportunity são independentes. UNKNOWN é excluído do denominador. Recommendation exige cobertura ≥60%; Opportunity ≥40%. Comissão jamais participa de Recommendation.

## ADR-012 — Assessments são snapshots imutáveis

Cada avaliação cria versão nova e preserva pilares, evidências, unknowns e rationale. Não existe alteração de assessment histórico.
## ADRs V1-D

- Campanha referencia snapshot de assessment imutável.
- Campanha é família de experimentos, não um post.
- BLOCK/NOT_RECOMMENDED nunca geram campanha.
- Campanha orgânica exige aprovação explícita antes de ativação.
- Qualquer gasto futuro exige aprovação financeira separada.
- Link de afiliado permanece manual até integração oficial.
- Warnings de Trust Gate propagam para criativos futuros.
- Claims OWNED_AND_TESTED exigem evidência explícita.

## ADRs V1-E

- Criativo nasce somente de campanha `APPROVED` e preserva snapshots.
- Templates são determinísticos, locais e editáveis; `FUTURE_AI` não chama providers nesta fase.
- Compliance central verifica hook, roteiro, CTA e textos das cenas.
- Warnings e disclosure propagam obrigatoriamente; UNKNOWN não vira fato.
- Approval `CREATIVE` congela o conteúdo submetido e não renderiza nem publica.
- Variantes preservam parent, grupo e rastreabilidade até campanha/assessment/candidato.
- A interface apresenta pt-BR, nomes humanos e poucos códigos técnicos; UUIDs e enums permanecem internos.
- Human-in-the-loop é seletivo: ações futuras seguras e sem custo poderão automatizar, enquanto riscos e exceções exigem revisão e qualquer gasto exige autorização explícita.
# V1-F.1a decisions

- Local-first: no required paid API, HTTP service, automatic download or publication.
- Asset paths are relative and resolved only inside the configured media root; filenames are generated UUIDs.
- Asset removal is logical deactivation in this phase so historical use is not destroyed.
- Jobs may be created manually only from `APPROVED` creatives and remain `QUEUED`; the global Kill Switch does not block this manual intent.
- FFmpeg/FFprobe diagnostics use argument arrays, `shell=False`, captured output and timeout. TTS is only diagnosed in F.1a and no fake audio is produced.
- Image validation uses local deterministic format parsing in F.1a, avoiding an undeclared runtime download. A dedicated decoder library may replace it later.
- Fake pipeline completion means only that orchestration was tested; it never creates output paths or claims that playable media exists.
- A second start is prevented by an atomic conditional database update. Active cancellation is observed between pipeline stages; terminal jobs cannot be restarted or canceled.
- LOCAL preflight requires FFmpeg and FFprobe. Piper is required only when at least one narrated scene has a speaker other than `NONE`; silent/text-only scenes remain valid.
- Piper receives narration through stdin, and all process calls use argument arrays with `shell=False`. Creative text and visual instructions are never interpreted as commands or FFmpeg arguments.
- Final media is promoted atomically only after FFprobe validation. Invalid output remains diagnostic/intermediate and is not published as a valid job path.
- Piper remains behind the `VoiceRenderer` contract and supports either a configurable CLI executable or `python -m <module>` invocation. This avoids coupling the domain to one repository/distribution.
- Voice models and companion configuration files have their own licenses. Operators must verify commercial-use rights before configuring a model; the project does not bundle or download voices.

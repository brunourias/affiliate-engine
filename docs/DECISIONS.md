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

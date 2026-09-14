# Affiliate Engine — Especificação mestre consolidada

## Missão

Construir progressivamente um agente de curadoria e crescimento orientado por dados. O sistema analisa muito, descarta muito, recomenda pouco, explica bem e aprende. A marca pesquisa antes de o consumidor comprar e prioriza confiança de longo prazo sobre comissão pontual.

## Métricas e finanças

A validação inicial é R$ 1.000/mês em comissões confirmadas; a North Star de longo prazo é lucro líquido atribuível. Comissão estimada, pendente e confirmada, custo e lucro permanecem conceitos separados.

## Decisão editorial

Trust Gate (`PASS`, `WARN`, `BLOCK`, `INSUFFICIENT_EVIDENCE`) é eliminatório. Recommendation Score mede qualidade editorial sem comissão. Opportunity Score mede interesse comercial. Preço é expresso por Price Verdict e PriceToBuy, não por um quarto score obrigatório. Um produto bloqueado nunca vira recomendação, independentemente da oportunidade.

## Evidência e transparência

Afirmações relevantes devem apontar para evidências e snapshots, com origem, captura e frescor. Ausência de dados deve ser explícita. Nunca alegar teste físico, estoque, urgência, preço ou desempenho sem comprovação. Níveis futuros: analisado, validado e testado por nós.

## Conteúdo e campanhas

Conteúdo parte de investigação e descoberta útil, não de geração genérica em volume. Produto e campanha são entidades distintas. Pilares iniciais: compra inteligente, oportunidade e descoberta. Vereditos podem recomendar comprar, esperar ou não comprar.

## Autonomia e segurança

Pesquisa e análise sem custo podem ser automatizadas quando implementadas. Publicação orgânica exige aprovação de campanha. Qualquer gasto, serviço pago, compra, anúncio ou decisão estratégica importante exige aprovação explícita. Silêncio nunca autoriza custo.

## Estratégia técnica

Local-first, cloud-ready, free-first; monólito modular, API REST, SQLite, migrations, logs estruturados e testes. Integrações ficam atrás de providers somente quando a fase demandar. Não há scraping não autorizado, integrações falsas, botões fictícios ou machine learning prematuro.

## Roadmap e limites atuais

A implementação preserva V1-A e V1-B.1 homologadas e acrescenta V1-B.2: categorias, execuções e sinais oficiais do Radar com proveniência concreta. Enriquecimento de produtos, preços, campanhas, scores, conteúdo, redes, analytics, Agent Chat e audiência própria pertencem às fases posteriores descritas em `ROADMAP.md`.

const LABELS: Record<string, string> = {
  AVAILABLE: 'Disponível',
  PAUSED: 'Pausado',
  PENDING: 'Pendente',
  RUNNING: 'Em execução',
  COMPLETED: 'Concluída',
  FAILED: 'Falhou',
  CANCELED: 'Cancelada',
  APPROVED: 'Aprovada',
  DRAFT: 'Rascunho',
  READY_FOR_REVIEW: 'Pronto para revisão',
  ARCHIVED: 'Arquivado',
  REJECTED: 'Rejeitada',
  INFO: 'Informativa',
  SUCCESS: 'Sucesso',
  WARNING: 'Atenção',
  ERROR: 'Erro',
  CRITICAL: 'Crítica',
  STRATEGIC: 'Estratégica',
  FINANCIAL: 'Financeira',
  CAMPAIGN: 'Campanha',
  APPROVAL: 'Aprovação',
  AGENT_TASK: 'Tarefa',
  OPERATOR: 'Operador',
  SYSTEM: 'Sistema',
  SYSTEM_HEARTBEAT: 'Heartbeat do sistema',
  CONTROLLED_FAILURE: 'Falha controlada',
  operational: 'Operacional',
  current: 'Atualizadas',
  separate: 'Processo separado',
  not_configured: 'Não configuradas',
  UNKNOWN: 'Sem referência suficiente',
  VERIFIED: 'Verificado',
  INVESTIGATING: 'Investigando',
  SUFFICIENT_EVIDENCE: 'Evidências suficientes',
  STALE: 'Desatualizado',
  CURRENT: 'Atual',
  OWNED_AND_TESTED: 'Testado por nós',
  DATA_ANALYZED: 'Dados analisados',
  COMMUNITY_VALIDATED: 'Validado pela comunidade',
  FORBIDDEN: 'Proibida',
  UNAUTHORIZED: 'Não autorizada',
  DEGRADED: 'Degradada',
  NOT_SUPPORTED: 'Não suportada',
  NOT_CONFIGURED: 'Não configurado',
  NOT_APPLICABLE: 'Não aplicável',
  UNAVAILABLE: 'Indisponível',
  ANONYMOUS: 'Anônimo',
  ENV_ACCESS_TOKEN: 'Token do ambiente',
  PARTIAL: 'Parcial',
  MANUAL: 'Manual',
  GENERIC: 'Genérico', SHORT_VIDEO: 'Vídeo curto', STATIC_POST: 'Post estático', CAROUSEL: 'Carrossel', STORY: 'Story', LONG_VIDEO_CONCEPT: 'Conceito de vídeo longo',
  TIKTOK: 'TikTok', INSTAGRAM_REELS: 'Instagram Reels', YOUTUBE_SHORTS: 'YouTube Shorts', FACEBOOK_REELS: 'Facebook Reels', WHATSAPP: 'WhatsApp', WEBSITE: 'Site',
  AVATAR: 'Avatar', TEXT: 'Texto', COMPARISON: 'Comparação', PROS_CONS: 'Prós e contras', PRICE: 'Preço', CTA: 'Chamada para ação', BROLL: 'Imagens de apoio', MIXED: 'Misto',
  NARRATOR: 'Narrador', NONE: 'Nenhum', SMART_BUYING: 'Compra inteligente', OPPORTUNITY: 'Oportunidade', DISCOVERY: 'Descoberta', PROBLEM_SOLUTION: 'Problema e solução', PRICE_ALERT: 'Alerta de preço', REVIEW: 'Análise', LIMITATION_FIRST: 'Limitações primeiro', EDUCATION: 'Educativo',
  NEW: 'Novo', RADAR_SIGNAL: 'Radar', MERCADO_LIVRE: 'Mercado Livre',
  NOT_READY: 'Ainda não está pronto', MISSING: 'Ausente', COVERED: 'Coberto',
  campaignApproved: 'Campanha aprovada', hook: 'Hook', bodyScript: 'Roteiro', cta: 'Chamada para ação', sceneCount: 'Quantidade de cenas', disclosure: 'Aviso de afiliação', warningCoverage: 'Cobertura dos alertas', compliance: 'Conformidade',
  CREATIVE_REVIEW: 'Revisão de criativo', CREATIVE: 'Criativo',
  HOOK: 'Abertura', BENEFIT: 'Benefício', LIMITATION: 'Limitação', CONCLUSION: 'Conclusão',
  CONTEXT: 'Contexto', EVIDENCE: 'Evidência', DISCLOSURE: 'Aviso de afiliação',
  QUESTIONING: 'Questionando', APPROVING: 'Aprovando', NEUTRAL: 'Neutro',
  BEST_ON_MARKET_UNSUPPORTED: 'Melhor do mercado sem evidência',
  LOWEST_PRICE_UNVERIFIED: 'Menor preço não verificado',
  NO_DEFECTS_CLAIM: 'Alegação de ausência de defeitos',
  ONE_HUNDRED_PERCENT_RECOMMENDED: 'Recomendação 100% não permitida',
  OWN_TEST_CLAIM: 'Alegação de teste próprio',
  PRICE_PROMOTION_CLAIM: 'Alegação promocional de preço',
  BUY_NOW_CTA: 'CTA de compra imediata',
  QUERY: 'Consulta',
  ITEM: 'Item',
  PRODUCT: 'Produto',
  USER_PRODUCT: 'User Product',
  TREND_GLOBAL: 'Tendência geral',
  TREND_CATEGORY: 'Tendência por categoria',
  HIGHLIGHT_CATEGORY: 'Mais vendidos',
  TRENDS_GLOBAL: 'Tendências gerais',
  TRENDS_CATEGORY: 'Tendências por categoria',
  HIGHLIGHTS_CATEGORY: 'Mais vendidos',
  PASS: 'Aprovado', WARN: 'Atenção', BLOCK: 'Bloqueado', INSUFFICIENT_EVIDENCE: 'Evidências insuficientes',
  EXCELLENT: 'Excelente', VERY_GOOD: 'Muito bom', GOOD: 'Bom', ACCEPTABLE_WITH_RESERVATIONS: 'Aceitável com ressalvas', NOT_RECOMMENDED: 'Não recomendado',
  BUY_NOW: 'Comprar agora', WORTH_IT: 'Vale a pena', WAIT_FOR_BETTER_PRICE: 'Esperar preço melhor',
  EXCELLENT_PRICE: 'Preço excelente', GOOD_PRICE: 'Bom preço', FAIR_PRICE: 'Preço justo', EXPENSIVE: 'Caro', AVOID_AT_THIS_PRICE: 'Evitar neste preço',
  QUALITY_RELIABILITY: 'Qualidade / confiabilidade', VALUE_FOR_MONEY: 'Valor pelo preço', BUYER_EXPERIENCE: 'Experiência', UTILITY_DIFFERENTIAL: 'Utilidade / diferencial', PURCHASE_SAFETY_SELLER: 'Segurança / vendedor', ALTERNATIVES: 'Alternativas', EVIDENCE_STRENGTH: 'Força das evidências', DEMAND_INTEREST: 'Demanda / interesse', TREND_MOMENTUM: 'Tendência', CONVERSION_POTENTIAL: 'Conversão', CONTENT_POTENTIAL: 'Potencial de conteúdo', TIMING_SEASONALITY: 'Timing / sazonalidade', COMPETITION: 'Concorrência', COMMISSION: 'Comissão', COMMERCIAL_DIFFERENTIATION: 'Diferencial comercial',
};

export const label = (value: string) => LABELS[value] ?? value;

const ACTION_LABELS: Record<string, string> = {
  CREATIVE_APPROVED: 'Criativo aprovado', CREATIVE_REJECTED: 'Criativo rejeitado', CREATIVE_SUBMITTED: 'Criativo enviado para revisão',
  CREATIVE_CREATED: 'Criativo criado', CREATIVE_UPDATED: 'Criativo atualizado', CREATIVE_TEMPLATE_GENERATED: 'Estrutura inicial do criativo gerada',
  CREATIVE_TEMPLATE_OVERWRITTEN: 'Estrutura do criativo regenerada', CREATIVE_SCENE_ADDED: 'Cena adicionada', CREATIVE_SCENE_UPDATED: 'Cena atualizada',
  CREATIVE_SCENE_REMOVED: 'Cena removida', CREATIVE_VARIANT_CREATED: 'Variante de criativo criada', CREATIVE_ARCHIVED: 'Criativo arquivado',
  APPROVAL_APPROVED: 'Solicitação aprovada', APPROVAL_REJECTED: 'Solicitação rejeitada', CAMPAIGN_CREATED: 'Campanha criada', CAMPAIGN_UPDATED: 'Campanha atualizada',
  CAMPAIGN_SUBMITTED: 'Campanha enviada para aprovação', CAMPAIGN_APPROVED: 'Campanha aprovada', CAMPAIGN_REJECTED: 'Campanha rejeitada', CAMPAIGN_PAUSED: 'Campanha pausada',
  CAMPAIGN_ARCHIVED: 'Campanha arquivada', CAMPAIGN_CHANNEL_ADDED: 'Canal adicionado à campanha', CAMPAIGN_ANGLE_ADDED: 'Ângulo adicionado à campanha',
  CAMPAIGN_EXPERIMENT_ADDED: 'Experimento adicionado à campanha', TASK_CREATED: 'Tarefa criada', TASK_RUNNING: 'Tarefa iniciada', TASK_COMPLETED: 'Tarefa concluída',
  TASK_FAILED: 'Tarefa com falha', TASK_PAUSED: 'Tarefa pausada', TASK_CANCELED: 'Tarefa cancelada', CURATOR_ASSESSMENT_CREATED: 'Avaliação editorial criada',
  CURATOR_CANDIDATE_CREATED: 'Candidato criado', CURATOR_CANDIDATE_CREATED_FROM_RADAR: 'Candidato criado a partir do Radar', CURATOR_CANDIDATE_UPDATED: 'Candidato atualizado',
  CURATOR_CANDIDATE_ARCHIVED: 'Candidato arquivado', CURATOR_CANDIDATE_REOPENED: 'Candidato reaberto', CURATOR_EVIDENCE_ADDED: 'Evidência adicionada',
  CURATOR_EVIDENCE_UPDATED: 'Evidência atualizada', CURATOR_EVIDENCE_REMOVED: 'Evidência removida', SETTINGS_UPDATED: 'Configurações atualizadas', AUTOMATION_PAUSED: 'Automação pausada',
  AUTOMATION_RESUMED: 'Automação reativada', MARKETPLACE_DIAGNOSTICS_RUN: 'Diagnóstico do marketplace executado', MARKETPLACE_CAPABILITY_CHANGED: 'Capacidade do marketplace alterada',
  RADAR_CATEGORIES_SYNCED: 'Categorias do Radar sincronizadas', RADAR_RUN_STARTED: 'Execução do Radar iniciada', RADAR_RUN_COMPLETED: 'Execução do Radar concluída',
  RADAR_RUN_FAILED: 'Execução do Radar com falha', DEMO_DATA_CREATED: 'Dados demonstrativos criados',
};

const humanizeCode = (value: string) => {
  const words = value.toLocaleLowerCase('pt-BR').replaceAll('_', ' ');
  return words ? words[0].toLocaleUpperCase('pt-BR') + words.slice(1) : value;
};

export const actionLabel = (value: string) => ACTION_LABELS[value] ?? humanizeCode(value);
export const entityLabel = (value: string) => label(value);

const CREATIVE_STATUS_LABELS: Record<string, string> = {
  DRAFT: 'Rascunho',
  READY_FOR_REVIEW: 'Pronto para revisão',
  APPROVED: 'Aprovado',
  REJECTED: 'Rejeitado',
  ARCHIVED: 'Arquivado',
};

export const creativeStatusLabel = (value: string) => CREATIVE_STATUS_LABELS[value] ?? label(value);

export const money = (cents: number) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(cents / 100);

const explicitUtc = (value: string) => /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
export const parseUtcTimestamp = (value: string) => new Date(explicitUtc(value));

export const formatDateTime = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat('pt-BR', {
        dateStyle: 'short',
        timeStyle: 'short',
        timeZone: 'America/Sao_Paulo',
      }).format(parseUtcTimestamp(value))
    : '—';

export const date = formatDateTime;

export const statusTone = (status: string) =>
  ['COMPLETED', 'APPROVED', 'SUCCESS', 'AVAILABLE', 'healthy'].includes(status)
    ? 'success'
    : ['FAILED', 'REJECTED', 'ERROR', 'CRITICAL', 'UNAVAILABLE', 'UNAUTHORIZED', 'FORBIDDEN'].includes(status)
      ? 'danger'
      : ['PENDING', 'WARNING', 'DEGRADED', 'PARTIAL'].includes(status)
        ? 'warning'
        : status === 'RUNNING'
          ? 'info'
          : 'neutral';

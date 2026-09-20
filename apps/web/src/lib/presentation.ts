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
  OPERATOR: 'Operador',
  SYSTEM: 'Sistema',
  SYSTEM_HEARTBEAT: 'Heartbeat do sistema',
  CONTROLLED_FAILURE: 'Falha controlada',
  operational: 'Operacional',
  current: 'Atualizadas',
  separate: 'Processo separado',
  not_configured: 'Não configuradas',
  UNKNOWN: 'Sem referência suficiente',
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

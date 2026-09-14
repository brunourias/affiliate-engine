const LABELS: Record<string, string> = {
  AVAILABLE: 'Disponível',
  PAUSED: 'Pausado',
  PENDING: 'Pendente',
  RUNNING: 'Em execução',
  COMPLETED: 'Concluída',
  FAILED: 'Falhou',
  CANCELED: 'Cancelada',
  APPROVED: 'Aprovada',
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
  UNKNOWN: 'Não testado',
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

export const money = (cents: number) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(cents / 100);

export const date = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat('pt-BR', {
        dateStyle: 'short',
        timeStyle: 'short',
        timeZone: 'America/Sao_Paulo',
      }).format(new Date(value))
    : '—';

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

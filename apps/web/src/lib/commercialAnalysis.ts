import type { CommercialAnalysisStatus } from '../types';

export function commercialBlocker(value: string | null) {
  return ({
    OFFER_REQUIRED: 'É necessário vincular uma oferta específica.',
    ITEM_DETAILS_FORBIDDEN: 'O Mercado Livre não disponibilizou os detalhes desta oferta para a integração.',
    COMMERCIAL_DATA_UNAVAILABLE: 'Os dados comerciais necessários não estão disponíveis no momento.',
    CATALOG_DATA_UNAVAILABLE: 'Os dados oficiais do produto não estão disponíveis no momento.',
    ENRICHMENT_FAILED: 'Não foi possível atualizar as evidências comerciais.',
  }[value ?? ''] ?? (value ? 'Não foi possível obter todos os dados comerciais necessários.' : ''));
}

export function commercialFeedback(status: CommercialAnalysisStatus) {
  return ({
    NOT_STARTED: 'Análise comercial atualizada.',
    WAITING_FOR_OFFER: 'Análise executada. É necessário vincular uma oferta.',
    EVIDENCE_PARTIAL: 'Análise executada com dados comerciais parciais.',
    ASSESSMENT_AVAILABLE: 'Análise comercial atualizada.',
    FAILED: 'Não foi possível concluir a análise.',
  }[status]);
}

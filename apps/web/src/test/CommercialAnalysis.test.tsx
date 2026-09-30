import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { CommercialAnalysisActions } from '../components/CommercialAnalysisActions';
import { CuratorPage } from '../pages/Curator';
import type { CommercialAnalysisStatus } from '../types';

const opportunity = (status: CommercialAnalysisStatus = 'NOT_STARTED', blocker: string | null = null) => ({
  candidateId: 'candidate-1', catalogProductId: 'MLB123', title: 'Produto de teste', triageScore: 70,
  triageStatus: 'TRIAGE_HIGH', relevanceScore: null, sourceRunIds: ['run-1'], sourceCategoryIds: [], sourceCount: 1,
  commercialBindingPresent: status !== 'WAITING_FOR_OFFER', sourceItemId: status !== 'WAITING_FOR_OFFER' ? 'MLB456' : null,
  evidenceStatus: 'PARTIAL_EVIDENCE', evidenceLevel: 'PARTIAL', opportunityReviewStatus: 'COMMERCIAL_REVIEW' as const,
  opportunityReviewedAt: null, opportunityReviewReason: null, commercialAnalysisStatus: status,
  commercialAnalysisLastRunAt: null, commercialAnalysisBlocker: blocker,
});

function configureCurator(status: CommercialAnalysisStatus = 'NOT_STARTED', blocker: string | null = null) {
  vi.spyOn(api, 'candidates').mockResolvedValue([{ id: 'candidate-1', status: 'NEW', triageScore: 70 } as never]);
  vi.spyOn(api, 'opportunities').mockResolvedValue([opportunity(status, blocker)]);
  vi.spyOn(api, 'opportunityReviewSummary').mockResolvedValue({ pending: 2, investigate: 1, commercialReview: 1, dismissed: 3 });
  vi.spyOn(api, 'campaignHandoffSummary').mockResolvedValue({ notDecided: 0, approved: 0, rejected: 0, stale: 0 });
  return vi.spyOn(api, 'commercialAnalysisSummary').mockResolvedValue({ notStarted: 1, waitingForOffer: 0, evidencePartial: 0, assessmentAvailable: 0, failed: 0 });
}

describe('Commercial analysis operator UI', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('loads the commercial summary only after opening the commercial-review tab', async () => {
    const summary = configureCurator();
    render(<MemoryRouter><CuratorPage /></MemoryRouter>);
    await screen.findByText('Produto de teste');
    expect(summary).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /Análise comercial 1/ }));
    expect(await screen.findByText('Não iniciadas')).toBeInTheDocument();
    expect(summary).toHaveBeenCalledOnce();
    expect(screen.getByText('Análise comercial ainda não foi executada.')).toBeInTheDocument();
  });

  it('separates the candidate list from opportunities and keeps secondary card details closed', async () => {
    configureCurator('WAITING_FOR_OFFER', 'OFFER_REQUIRED');
    render(<MemoryRouter><CuratorPage /></MemoryRouter>);
    await screen.findByText('Produto de teste');
    expect(screen.queryByText('Todos os candidatos', { selector: 'h2' })).not.toBeInTheDocument();
    expect(screen.queryByText('Encontrado em uma execução.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Todos os candidatos' }));
    expect(await screen.findByRole('heading', { name: 'Todos os candidatos' })).toBeInTheDocument();
    expect(screen.queryByText('Oportunidades', { selector: 'h2' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Oportunidades' }));
    await screen.findByText('Produto de teste');
    fireEvent.click(screen.getByRole('button', { name: /Análise comercial 1/ }));
    await screen.findByText('Aguardando oferta');
    fireEvent.click(screen.getByRole('button', { name: 'Detalhes' }));
    expect(await screen.findByText((content) => content.includes('Encontrado em') && content.includes('execução'))).toBeInTheDocument();
  });

  it('shows translated partial-evidence blockers without a fatal error state', async () => {
    configureCurator('EVIDENCE_PARTIAL', 'ITEM_DETAILS_FORBIDDEN');
    render(<MemoryRouter><CuratorPage /></MemoryRouter>);
    await screen.findByText('Produto de teste');
    fireEvent.click(screen.getByRole('button', { name: /Análise comercial 1/ }));
    await screen.findByText('Evidências comerciais parciais');
    expect(screen.getByText('O Mercado Livre não disponibilizou os detalhes desta oferta para a integração.')).toBeInTheDocument();
    expect(screen.queryByText('ITEM_DETAILS_FORBIDDEN')).not.toBeInTheDocument();
  });

  it('requires batch confirmation, runs once, and refreshes the list and commercial summary', async () => {
    const summary = configureCurator('WAITING_FOR_OFFER', 'OFFER_REQUIRED');
    const batch = vi.spyOn(api, 'runCommercialAnalysisBatch').mockResolvedValue({ status: 'COMPLETED', requested: 1, processed: 1, assessmentAvailable: 0, waitingForOffer: 1, evidencePartial: 0, failed: 0, candidates: [] });
    render(<MemoryRouter><CuratorPage /></MemoryRouter>);
    await screen.findByText('Produto de teste');
    fireEvent.click(screen.getByRole('button', { name: /Análise comercial 1/ }));
    await screen.findByText('Executar análises comerciais');
    fireEvent.click(screen.getByRole('button', { name: 'Executar análises comerciais' }));
    expect(batch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(batch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Executar análises comerciais' }));
    const confirm = screen.getByRole('button', { name: 'Confirmar análise' });
    fireEvent.click(confirm); fireEvent.click(confirm);
    await waitFor(() => expect(batch).toHaveBeenCalledOnce());
    expect(await screen.findByText('Análise concluída: 0 análises disponíveis, 1 aguardando oferta, 0 com evidências parciais, 0 falhas.')).toBeInTheDocument();
    await waitFor(() => expect(summary.mock.calls.length).toBeGreaterThan(1));
  });

  it('runs an individual analysis once and keeps the card visible after an error', async () => {
    const reload = vi.fn();
    const failure = vi.spyOn(api, 'runCommercialAnalysis').mockRejectedValue(new Error('Falha controlada'));
    render(<MemoryRouter><CommercialAnalysisActions candidateId="candidate-1" status="FAILED" onDone={reload} /></MemoryRouter>);
    const retry = screen.getByRole('button', { name: 'Tentar novamente' });
    fireEvent.click(retry); fireEvent.click(retry);
    await waitFor(() => expect(failure).toHaveBeenCalledOnce());
    expect(await screen.findByRole('alert')).toHaveTextContent('Falha controlada');
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
  });

  it('prioritizes linking an offer before a waiting analysis rerun', () => {
    render(<MemoryRouter><CommercialAnalysisActions candidateId="candidate-1" status="WAITING_FOR_OFFER" onDone={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole('link', { name: 'Vincular oferta' })).toHaveClass('primary-button');
    expect(screen.getByRole('button', { name: 'Executar novamente' })).toHaveClass('ghost-button');
  });
});

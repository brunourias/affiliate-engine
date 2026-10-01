import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CreativePage } from '../pages/Creatives';

const response = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const scene = { id: 's1', creativeId: 'cr1', orderIndex: 0, sceneType: 'AVATAR', speaker: 'BRUNO', purpose: 'HOOK', narrationText: 'Hook', onScreenText: null, visualInstruction: null, avatarState: 'WARNING', durationSeconds: 4, requiredWarningCodes: [] };
const approval = { id: 'approval1', type: 'CREATIVE', status: 'PENDING', title: 'Aprovar', description: 'Revisão', entityType: 'CREATIVE', entityId: 'cr1', requestedPayload: {}, decidedAt: null, decisionReason: null, createdAt: '2026-09-23T10:00:00Z', updatedAt: '2026-09-23T10:00:00Z' };

function setup(initialStatus = 'DRAFT', ready = true) {
  let status = initialStatus;
  const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = String(input), method = init?.method ?? 'GET';
    if (url.endsWith('/creatives/cr1/submit-for-review') && method === 'POST') { status = 'READY_FOR_REVIEW'; return response(approval); }
    if (url.includes('/approvals?status=PENDING')) return response(status === 'READY_FOR_REVIEW' ? [approval] : []);
    if (url.endsWith('/creatives/cr1/scenes')) return response([scene]);
    if (url.endsWith('/creatives/cr1/readiness')) return response({ state: ready ? 'READY_FOR_REVIEW' : 'NOT_READY', creativeStatus: status, nextAction: ready ? 'READY_TO_SUBMIT' : 'COMPLETE_CONTENT', blockers: [], warnings: [], checks: { hook: true }, sceneCount: 1, compliance: { status: 'PASS', reasons: [], requiredWarningCoverage: [] } });
    if (url.endsWith('/creatives/cr1')) return response({ id: 'cr1', campaignId: 'cp1', experimentId: null, name: 'Cópia', status, contentType: 'SHORT_VIDEO', targetChannel: 'GENERIC', angleTypeSnapshot: null, objectiveSnapshot: 'EDUCATION', editorialVerdictSnapshot: 'WORTH_IT', priceVerdictSnapshot: 'FAIR_PRICE', title: 'Título', contentPremise: 'Premissa', hook: 'Hook', bodyScript: 'Roteiro', cta: 'Compare', estimatedDurationSeconds: 20, disclosureText: 'Afiliado', requiredWarnings: [], forbiddenClaims: [], generationMode: 'MANUAL', variantGroup: null, parentCreativeId: 'source', variantLabel: null, creationSource: 'CAMPAIGN_HANDOFF', creationKey: null, sourceCampaignApprovalId: null, sourceAssessmentId: null });
    if (url.endsWith('/campaigns/cp1')) return response({ id: 'cp1', name: 'Produto', status: 'APPROVED' });
    return response({});
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<MemoryRouter initialEntries={['/criativos/cr1']}><Routes><Route path="/criativos/:id" element={<CreativePage />} /><Route path="/aprovacoes/:id" element={<div>Aprovação aberta</div>} /></Routes></MemoryRouter>);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('envio do Creative para revisão', () => {
  it('envia DRAFT pronto, permanece na página, mostra confirmação e link para a Approval pendente', async () => {
    const fetchMock = setup();
    fireEvent.click(await screen.findByRole('button', { name: 'Enviar para revisão' }));
    expect(await screen.findByText('Criativo enviado para revisão.')).toBeInTheDocument();
    expect(await screen.findByText('Aguardando decisão humana.')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Revisar aprovação' })).toHaveAttribute('href', '/aprovacoes/approval1');
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/submit-for-review') && init?.method === 'POST')).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes('/approvals/approval1/') && init?.method === 'POST')).toBe(false);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/creatives/from-'))).toBe(false);
  });

  it('READY_FOR_REVIEW só apresenta link de revisão e não apresenta decisão na página do Creative', async () => {
    setup('READY_FOR_REVIEW');
    expect(await screen.findByRole('link', { name: 'Revisar aprovação' })).toHaveAttribute('href', '/aprovacoes/approval1');
    expect(screen.getByText('Aguardando decisão humana.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Aprovar' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Rejeitar' })).not.toBeInTheDocument();
  });

  it('estado inconsistente sem Approval oferece atualização, sem criar nova solicitação automaticamente', async () => {
    const fetchMock = setup('READY_FOR_REVIEW');
    fetchMock.mockImplementation(async (input: string | URL) => {
      const url = String(input);
      if (url.includes('/approvals?status=PENDING')) return response([]);
      if (url.endsWith('/creatives/cr1/scenes')) return response([scene]);
      if (url.endsWith('/creatives/cr1/readiness')) return response({ state: 'READY_FOR_REVIEW', nextAction: 'AWAITING_APPROVAL', checks: {}, sceneCount: 1, compliance: { status: 'PASS', reasons: [], requiredWarningCoverage: [] } });
      if (url.endsWith('/creatives/cr1')) return response({ id: 'cr1', campaignId: 'cp1', name: 'Cópia', status: 'READY_FOR_REVIEW', contentType: 'SHORT_VIDEO', targetChannel: 'GENERIC', title: 'Título', contentPremise: '', hook: '', bodyScript: '', cta: '', estimatedDurationSeconds: 20, disclosureText: '', requiredWarnings: [], forbiddenClaims: [], generationMode: 'MANUAL' });
      if (url.endsWith('/campaigns/cp1')) return response({ id: 'cp1', name: 'Produto', status: 'APPROVED' });
      return response({});
    });
    expect(await screen.findByText(/não foi localizada uma aprovação pendente/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Atualizar' })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes('/submit-for-review') && init?.method === 'POST')).toBe(false);
  });

  it('DRAFT não pronto não permite enviar para revisão', async () => {
    setup('DRAFT', false);
    await screen.findByText('Complete o conteúdo do criativo');
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Enviar para revisão' })).not.toBeInTheDocument());
  });

  it('duplo clique não envia o mesmo Creative duas vezes', async () => {
    const fetchMock = setup();
    const original = fetchMock.getMockImplementation();
    let release: ((value: Response) => void) | undefined;
    fetchMock.mockImplementation(async (input: string | URL, init?: RequestInit) => {
      if (String(input).endsWith('/creatives/cr1/submit-for-review')) return await new Promise<Response>(resolve => { release = resolve; });
      return original!(input, init);
    });
    const submit = await screen.findByRole('button', { name: 'Enviar para revisão' });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/submit-for-review') && init?.method === 'POST')).toHaveLength(1);
    release?.(await response(approval));
    expect(await screen.findByText('Criativo enviado para revisão.')).toBeInTheDocument();
  });
});

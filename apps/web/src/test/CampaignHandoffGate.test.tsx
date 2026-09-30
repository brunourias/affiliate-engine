import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CampaignHandoffGate } from '../components/CampaignHandoffGate';

const handoff = (status: 'NOT_DECIDED'|'APPROVED'|'REJECTED'|'STALE' = 'NOT_DECIDED', reason: string | null = null) => ({ candidateId:'c1', status, assessmentId:status==='NOT_DECIDED'?null:'a2', assessmentVersion:status==='NOT_DECIDED'?null:2, reviewedAt:status==='NOT_DECIDED'?null:'2026-09-30T12:00:00Z', reason, currentAssessmentId:'a2', currentAssessmentVersion:2, isCurrentAssessment:status!=='STALE' });
const assessment = { id:'a2', candidateId:'c1', assessmentVersion:2, trustGate:'PASS', trustReasons:[], trustWarnings:[], recommendationScore:null, recommendationCoveragePercent:0, recommendationLabel:null, opportunityScore:72, opportunityCoveragePercent:70, priceVerdict:'UNKNOWN', priceToBuyCents:null, editorialVerdict:'WORTH_IT', recommendationPillars:{}, opportunityPillars:{}, evidenceStatus:'SUFFICIENT_EVIDENCE', evidenceLevel:'HIGH', evaluatedAt:'2026-09-30T12:00:00Z', createdAt:'2026-09-30T12:00:00Z' };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function mockHttp(update: (body: Record<string, unknown>) => Response = body => json(handoff(body.status as 'APPROVED'|'REJECTED', body.reason as string | null))) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/campaign-handoff') && init?.method === 'PATCH') return update(JSON.parse(String(init.body)));
    if (url.endsWith('/campaign-handoff')) return json(handoff());
    if (url.endsWith('/assessments/a2')) return json(assessment);
    throw new Error(`Unexpected HTTP request: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

async function openDecision() {
  fireEvent.click(screen.getByRole('button', { name:'Revisar e encaminhar' }));
  await screen.findByRole('dialog');
}

function patchBodies(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === 'PATCH')
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)));
}

describe('CampaignHandoffGate HTTP payload', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('sends the typed reason in the actual APPROVED PATCH body', async () => {
    const fetchMock = mockHttp();
    render(<CampaignHandoffGate candidateId="c1" status="NOT_DECIDED" onDone={vi.fn()} />);
    await openDecision();
    fireEvent.change(screen.getByPlaceholderText('Motivo da decisão (opcional)'), { target:{ value:'Encaminhamento aprovado após revisão' } });
    fireEvent.click(screen.getByRole('button',{ name:'Encaminhar para campanha' }));
    await waitFor(() => expect(patchBodies(fetchMock)).toEqual([{ status:'APPROVED', assessmentId:'a2', reason:'Encaminhamento aprovado após revisão' }]));
    expect(screen.getByText('Autorizada para a próxima etapa. Nenhuma campanha foi criada automaticamente.')).toBeInTheDocument();
    expect(screen.queryByText(/Esta oportunidade está autorizada/i)).not.toBeInTheDocument();
  });

  it('sends the typed reason in the actual REJECTED PATCH body', async () => {
    const fetchMock = mockHttp();
    render(<CampaignHandoffGate candidateId="c1" status="NOT_DECIDED" onDone={vi.fn()} />);
    await openDecision();
    fireEvent.change(screen.getByPlaceholderText('Motivo da decisão (opcional)'), { target:{ value:'Não encaminhar neste momento' } });
    fireEvent.click(screen.getByRole('button',{ name:'Não encaminhar' }));
    await waitFor(() => expect(patchBodies(fetchMock)).toEqual([{ status:'REJECTED', assessmentId:'a2', reason:'Não encaminhar neste momento' }]));
    expect(screen.getByText('Motivo: Não encaminhar neste momento')).toBeInTheDocument();
  });

  it('sends reason null when the decision form is left empty', async () => {
    const fetchMock = mockHttp();
    render(<CampaignHandoffGate candidateId="c1" status="NOT_DECIDED" onDone={vi.fn()} />);
    await openDecision();
    fireEvent.click(screen.getByRole('button',{ name:'Encaminhar para campanha' }));
    await waitFor(() => expect(patchBodies(fetchMock)).toEqual([{ status:'APPROVED', assessmentId:'a2', reason:null }]));
  });

  it('reloads after ASSESSMENT_CHANGED without applying the decision again', async () => {
    const fetchMock = mockHttp(() => json({ detail:'ASSESSMENT_CHANGED' }, 409));
    const onDone = vi.fn();
    render(<CampaignHandoffGate candidateId="c1" status="NOT_DECIDED" onDone={onDone} />);
    await openDecision();
    fireEvent.click(screen.getByRole('button',{ name:'Encaminhar para campanha' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('A análise comercial mudou enquanto você revisava esta oportunidade.');
    expect(patchBodies(fetchMock)).toHaveLength(1);
    expect(onDone).toHaveBeenCalledOnce();
  });
});

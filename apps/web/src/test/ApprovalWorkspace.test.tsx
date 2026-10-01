import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Approvals } from '../pages/Operations';
import { ApprovalWorkspace } from '../pages/ApprovalWorkspace';
import type { Approval, Campaign, CampaignReadiness, Creative, CreativeReadiness } from '../types';

const now = '2026-10-01T12:00:00Z';
const campaign: Campaign = {
  id: 'camp-1', candidateId: 'candidate-1', assessmentId: 'assessment-1', name: 'Parafusadeira doméstica', status: 'PENDING_APPROVAL', objective: 'CONVERSION', editorialVerdictSnapshot: 'WORTH_IT', trustGateSnapshot: 'PASS', recommendationScoreSnapshot: 78, opportunityScoreSnapshot: 83, priceVerdictSnapshot: 'GOOD_PRICE', campaignPriority: 'HIGH', targetAudience: 'Pessoas que fazem reparos em casa', editorialPositioning: 'Compra consciente', primaryMessage: 'Compare antes de escolher', affiliateUrl: 'https://example.test/affiliate', affiliateUrlSource: 'MANUAL', affiliateUrlVerifiedAt: now, disclosureText: 'Podemos receber comissão.', ctaStrategy: 'Veja os detalhes', requiresFinancialSpend: false, trustWarningsSnapshot: [], requiredDisclosures: [], requiredWarnings: [], forbiddenClaims: [], createdAt: now, updatedAt: now, approvedAt: null, rejectedAt: null,
};
const validReadiness: CampaignReadiness = { state: 'PENDING_APPROVAL', campaignStatus: 'PENDING_APPROVAL', checks: {}, blockers: [], warnings: [], nextAction: 'AWAITING_APPROVAL', channelCount: 1, angleCount: 1, experimentCount: 1 };
const approvalBase = (overrides: Partial<Approval> = {}): Approval => ({ id: 'approval-1', type: 'CAMPAIGN', status: 'PENDING', title: 'Parafusadeira — campanha de teste', description: 'Campaign: Parafusadeira\nOpportunity Score: 83\nResumo completo auditável.', entityType: 'CAMPAIGN', entityId: 'camp-1', requestedPayload: { requiresFinancialSpend: false }, decidedAt: null, decisionReason: null, createdAt: now, updatedAt: now, ...overrides });
function response(body: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })); }

let records: Approval[];
let currentApproval: Approval;
let currentCampaign: Campaign;
let currentReadiness: CampaignReadiness;
let currentCreativeReadiness: CreativeReadiness;
let currentCreative: Creative;
let failDecisionCode: string | null;
let fetchMock: ReturnType<typeof vi.fn>;

function setup({ route = '/aprovacoes/approval-1', approval = approvalBase(), list = [approvalBase(), approvalBase({ id: 'approval-2', type: 'STRATEGIC', title: 'Solicitação estratégica', description: 'NÃO EXIBIR: descrição extensa', entityType: null, entityId: null, requestedPayload: { source: 'local' } }), approvalBase({ id: 'approval-3', status: 'REJECTED', decisionReason: 'Revisar origem', decidedAt: now })], readiness = validReadiness, creativeReadiness, spend = false, decisionFailure = null }: { route?: string; approval?: Approval; list?: Approval[]; readiness?: CampaignReadiness; creativeReadiness?: CreativeReadiness; spend?: boolean; decisionFailure?: string | null } = {}) {
  records = list.map(item => ({ ...item }));
  currentApproval = { ...approval, requestedPayload: spend ? { ...(approval.requestedPayload ?? {}), requiresFinancialSpend: true } : approval.requestedPayload };
  currentCampaign = { ...campaign, requiresFinancialSpend: spend };
  currentReadiness = readiness;
  currentCreativeReadiness = creativeReadiness ?? { state: 'READY_FOR_REVIEW', creativeStatus: 'READY_FOR_REVIEW', checks: {}, sceneCount: 2, blockers: [], warnings: [], nextAction: 'AWAITING_APPROVAL', compliance: { status: 'PASS', reasons: [], requiredWarningCoverage: [] } };
  currentCreative = { id: 'creative-1', campaignId: 'camp-1', experimentId: null, name: 'Criativo teste', status: 'READY_FOR_REVIEW', contentType: 'SHORT_VIDEO', targetChannel: 'TIKTOK', angleTypeSnapshot: 'HOME_USE', objectiveSnapshot: 'CONVERSION', editorialVerdictSnapshot: 'WORTH_IT', priceVerdictSnapshot: 'FAIR_PRICE', title: 'Título atual', contentPremise: 'Premissa atual', hook: 'Hook atual', bodyScript: 'Roteiro atual', cta: 'CTA atual', estimatedDurationSeconds: 20, disclosureText: 'Aviso de afiliação', requiredWarnings: [{ code: 'SAFETY', message: 'Use proteção.' }], forbiddenClaims: ['BEST_ON_MARKET_UNSUPPORTED'], generationMode: 'MANUAL', variantGroup: null, parentCreativeId: null, variantLabel: null, creationSource: 'CAMPAIGN_APPROVAL', creationKey: null, sourceCampaignApprovalId: 'source-approval', sourceAssessmentId: 'assessment-1' };
  failDecisionCode = decisionFailure;
  fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = String(input); const method = init?.method ?? 'GET';
    if (url.endsWith('/approvals') && method === 'GET') return response(records);
    if (url.endsWith('/approvals/approval-1/approve') && method === 'POST' || url.endsWith('/approvals/approval-1/reject') && method === 'POST') {
      if (failDecisionCode) {
        const code = failDecisionCode; failDecisionCode = null;
        if (code === 'APPROVAL_DECISION_CONFLICT') currentApproval = { ...currentApproval, status: 'APPROVED', decidedAt: now };
        if (code === 'CAMPAIGN_APPROVAL_INVALIDATED') currentReadiness = { ...currentReadiness, blockers: [{ code: 'ASSESSMENT_OUTDATED', message: 'A análise de origem mudou.' }] };
        if (code === 'CREATIVE_APPROVAL_INVALIDATED') currentCreativeReadiness = { ...currentCreativeReadiness, blockers: [{ code: 'CREATIVE_CHANGED', message: 'O conteúdo do criativo mudou.' }] };
        return response({ detail: { code, message: 'Erro seguro para teste.', blockers: currentReadiness.blockers } }, 409);
      }
      const status = url.endsWith('/approve') ? 'APPROVED' : 'REJECTED';
      const body = JSON.parse(String(init?.body));
      currentApproval = { ...currentApproval, status, decisionReason: body.reason, decidedAt: now, updatedAt: now };
      return response(currentApproval);
    }
    if (url.endsWith(`/approvals/${currentApproval.id}`)) return response(currentApproval);
    if (url.endsWith('/creatives/creative-1')) return response(currentCreative);
    if (url.endsWith('/creatives/creative-1/readiness')) return response(currentCreativeReadiness);
    if (url.endsWith('/campaigns/camp-1')) return response(currentCampaign);
    if (url.endsWith('/campaigns/camp-1/readiness')) return response(currentReadiness);
    if (url.endsWith('/campaigns/camp-1/channels')) return response([{ id: 'channel-1', campaignId: 'camp-1', channel: 'TIKTOK', enabled: true, publicationMode: 'MANUAL', platformNotes: null }]);
    if (url.endsWith('/campaigns/camp-1/angles')) return response([{ id: 'angle-1', campaignId: 'camp-1', angleType: 'SMART_BUYING', title: 'Compra consciente', premise: 'Compare', targetSegment: null, priority: 1, status: 'ACTIVE' }]);
    if (url.endsWith('/campaigns/camp-1/experiments')) return response([{ id: 'experiment-1', campaignId: 'camp-1', angleId: 'angle-1', hypothesis: 'Teste de mensagem', status: 'PLANNED', hookStrategy: null, ctaStrategy: null, targetChannel: 'TIKTOK', variantGroup: null }]);
    return response({});
  });
  vi.stubGlobal('fetch', fetchMock);
  return render(<MemoryRouter initialEntries={[route]}><Routes><Route path="/aprovacoes" element={<Approvals />} /><Route path="/aprovacoes/:id" element={<ApprovalWorkspace />} /><Route path="/campanhas/:id" element={<div>Campaign destination</div>} /><Route path="/curator/:id" element={<div>Curator destination</div>} /></Routes></MemoryRouter>);
}

beforeEach(() => { vi.stubGlobal('prompt', vi.fn()); });
afterEach(() => { vi.unstubAllGlobals(); });

describe('Approval Decision Workspace', () => {
  it('central mostra métricas, filtros por status/tipo e cards sem descrição longa nem decisão direta', async () => {
    setup({ route: '/aprovacoes' });
    expect(await screen.findByText('Pendentes')).toBeInTheDocument();
    expect(screen.getByText('Aprovadas')).toBeInTheDocument();
    expect(screen.getByText('Rejeitadas')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Revisar' }).some(link => link.getAttribute('href') === '/aprovacoes/approval-1')).toBe(true);
    expect(screen.getByRole('link', { name: 'Ver decisão' })).toHaveAttribute('href', '/aprovacoes/approval-3');
    expect(screen.queryByText('NÃO EXIBIR: descrição extensa')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Aprovar' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Rejeitar' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Filtrar status'), { target: { value: 'REJECTED' } });
    expect(screen.getByText('1 solicitação')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Filtrar status'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Filtrar tipo'), { target: { value: 'STRATEGIC' } });
    expect(screen.getByText('Solicitação estratégica')).toBeInTheDocument();
    expect(screen.queryByText('Parafusadeira — campanha de teste')).not.toBeInTheDocument();
    expect(document.querySelector('.table-wrap')).not.toBeInTheDocument();
    expect(prompt).not.toHaveBeenCalled();
  });

  it('central identifica Approval de Creative pelo nome humano e mantém CTA para workspace de decisão', async () => {
    const creativeApproval = approvalBase({ id: 'approval-creative', type: 'CREATIVE', entityType: 'CREATIVE', entityId: 'creative-1', title: 'Revisar criativo' });
    setup({ route: '/aprovacoes', list: [creativeApproval] });
    expect(await screen.findAllByText('Criativo')).not.toHaveLength(0);
    expect(screen.getByRole('link', { name: 'Revisar' })).toHaveAttribute('href', '/aprovacoes/approval-creative');
    expect(screen.queryByText('CREATIVE')).not.toBeInTheDocument();
  });

  it('workspace genérico permanece para Creative sem entidade associada e mostra resumo auditável e payload secundário', async () => {
    setup({ approval: approvalBase({ type: 'CREATIVE', entityType: null, entityId: null, requestedPayload: { rendersMedia: false }, description: 'Resumo preservado\nsegunda linha' }) });
    expect(await screen.findByRole('heading', { name: 'Parafusadeira — campanha de teste' })).toBeInTheDocument();
    expect(screen.getByText((_content, element) => element?.tagName === 'PRE' && element.textContent === 'Resumo preservado\nsegunda linha')).toBeInTheDocument();
    expect(screen.getByText('Payload solicitado')).toBeInTheDocument();
    expect(screen.getByText(/rendersMedia/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/campaigns/'))).toBe(false);
    expect(screen.getByLabelText('Motivo da decisão (opcional)')).toBeInTheDocument();
  });

  it('Approval Campaign carrega contexto, readiness, canais e estrutura planejada', async () => {
    setup();
    expect(await screen.findByText('Condição atual para aprovação')).toBeInTheDocument();
    expect(screen.getByText('Os requisitos atuais continuam válidos.')).toBeInTheDocument();
    expect(screen.getByText('Parafusadeira doméstica')).toBeInTheDocument();
    expect(screen.getByText('Pessoas que fazem reparos em casa')).toBeInTheDocument();
    expect(screen.getByText('TikTok')).toBeInTheDocument();
    expect(screen.getByText('Campanha atual')).toBeInTheDocument();
    expect(screen.getByText('Qualidade das evidências no envio')).toBeInTheDocument();
    expect(screen.getByText('Pontuação de recomendação')).toBeInTheDocument();
    expect(screen.getByText('Pontuação de oportunidade')).toBeInTheDocument();
    expect(screen.getByText('Veredito de preço')).toBeInTheDocument();
    expect(screen.getByText('Abrir campanha')).toHaveAttribute('href', '/campanhas/camp-1');
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/approvals/approval-1'))).toBe(true);
    for (const endpoint of ['/campaigns/camp-1', '/campaigns/camp-1/readiness', '/campaigns/camp-1/channels', '/campaigns/camp-1/angles', '/campaigns/camp-1/experiments']) expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith(endpoint))).toBe(true);
  });

  it('confirma Aprovar inline; cancelar não chama API e confirmar envia motivo exatamente uma vez', async () => {
    setup();
    fireEvent.change(await screen.findByLabelText('Motivo da decisão (opcional)'), { target: { value: '  homologação aprovada  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }));
    expect(screen.getByText('Confirmar aprovação desta campanha?')).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/approve') && init?.method === 'POST')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByText('Confirmar aprovação desta campanha?')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar aprovação' }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/approve') && init?.method === 'POST')).toHaveLength(1));
    const decisionCall = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith('/approve') && init?.method === 'POST');
    expect(JSON.parse(String(decisionCall?.[1]?.body))).toEqual({ reason: 'homologação aprovada' });
    expect(await screen.findByText('Decisão desta solicitação')).toBeInTheDocument();
    expect(screen.getAllByText('Aprovada').length).toBeGreaterThan(0);
    expect(screen.getByText('homologação aprovada')).toBeInTheDocument();
    expect(screen.queryByLabelText('Motivo da decisão (opcional)')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/creatives/from-campaign/'))).toBe(false);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('instagram-publish'))).toBe(false);
  });

  it('bloqueia apenas Aprovar quando readiness tem blockers e permite Reject', async () => {
    const blockers = [{ code: 'TARGET_AUDIENCE_REQUIRED', message: 'Informe o público-alvo.' }];
    setup({ readiness: { ...validReadiness, blockers } });
    expect(await screen.findByText('A campanha mudou desde o envio e não pode ser aprovada neste momento.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Aprovar' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Rejeitar' })).toBeEnabled();
    expect(screen.getByText('Informe o público-alvo.')).toBeInTheDocument();
  });

  it('Assessment desatualizado mostra orientação humana e link para oportunidade, sem mostrar o código', async () => {
    setup({ readiness: { ...validReadiness, blockers: [{ code: 'ASSESSMENT_OUTDATED', message: 'A análise de origem mudou.' }] } });
    expect(await screen.findByText('A análise comercial mudou após o envio desta campanha.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Abrir oportunidade' })).toHaveAttribute('href', '/curator/candidate-1');
    expect(screen.queryByText('ASSESSMENT_OUTDATED')).not.toBeInTheDocument();
  });

  it('blocker editorial orienta Curadoria e gasto financeiro aparece como aviso separado', async () => {
    setup({ readiness: { ...validReadiness, blockers: [{ code: 'TRUST_GATE_BLOCKED', message: 'A qualidade das evidências não permite avançar.' }] }, spend: true });
    expect(await screen.findByText('A condição editorial atual não permite aprovação.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Abrir oportunidade' })).toHaveAttribute('href', '/curator/candidate-1');
    expect(screen.getAllByText((_content, element) => element?.textContent?.includes('Esta campanha prevê gasto financeiro, que continua dependendo de autorização separada.') ?? false).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /autorizar gasto/i })).not.toBeInTheDocument();
  });

  it('rejeitar exige confirmação, permite reason vazio e atualiza status/dados sem reenvio automático', async () => {
    setup();
    fireEvent.click(await screen.findByRole('button', { name: 'Rejeitar' }));
    expect(screen.getByText('Confirmar rejeição desta solicitação?')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar rejeição' }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/reject') && init?.method === 'POST')).toHaveLength(1));
    const call = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith('/reject') && init?.method === 'POST');
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ reason: null });
    expect(await screen.findByText('A campanha voltou para revisão e pode ser corrigida e reenviada.')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Abrir campanha' }).every(link => link.getAttribute('href') === '/campanhas/camp-1')).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('submit-for-approval'))).toBe(false);
  });

  it('invalidated refresca Approval, Campaign e readiness e mantém rejeição disponível', async () => {
    setup({ decisionFailure: 'CAMPAIGN_APPROVAL_INVALIDATED' });
    fireEvent.click(await screen.findByRole('button', { name: 'Aprovar' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar aprovação' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('A campanha mudou desde o envio e precisa ser revisada antes da aprovação.');
    expect(await screen.findByText('A análise comercial mudou após o envio desta campanha.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Aprovar' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Rejeitar' })).toBeEnabled();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/approvals/approval-1')).length).toBeGreaterThan(1);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/campaigns/camp-1/readiness')).length).toBeGreaterThan(1);
  });

  it('decision conflict refresca estado real e remove composer se outra sessão já decidiu', async () => {
    setup({ decisionFailure: 'APPROVAL_DECISION_CONFLICT' });
    fireEvent.click(await screen.findByRole('button', { name: 'Rejeitar' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar rejeição' }));
    expect(await screen.findByText('Decisão desta solicitação')).toBeInTheDocument();
    expect(screen.getAllByText('Aprovada').length).toBeGreaterThan(0);
    expect(screen.queryByLabelText('Motivo da decisão (opcional)')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/campaigns/camp-1/readiness')).length).toBeGreaterThan(1);
  });

  it('duplo clique enquanto busy não duplica o POST de decisão', async () => {
    let release: ((value: Response) => void) | undefined;
    setup();
    fetchMock.mockImplementation(async (input: string | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/approvals/approval-1/approve') && init?.method === 'POST') return await new Promise<Response>(resolve => { release = resolve; });
      if (url.endsWith('/approvals/approval-1')) return response(currentApproval);
      if (url.endsWith('/campaigns/camp-1')) return response(currentCampaign);
      if (url.endsWith('/campaigns/camp-1/readiness')) return response(currentReadiness);
      if (url.endsWith('/campaigns/camp-1/channels')) return response([]);
      if (url.endsWith('/campaigns/camp-1/angles')) return response([]);
      if (url.endsWith('/campaigns/camp-1/experiments')) return response([]);
      return response([]);
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Aprovar' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar aprovação' }));
    fireEvent.click(screen.getByRole('button', { name: 'Aprovando…' }));
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/approve') && init?.method === 'POST')).toHaveLength(1);
    currentApproval = { ...currentApproval, status: 'APPROVED', decidedAt: now };
    release?.(await response(currentApproval));
    expect(await screen.findByText('Decisão desta solicitação')).toBeInTheDocument();
  });

  it('Approval histórica preserva seu status próprio mesmo se Campaign atual estiver aprovada', async () => {
    setup({ approval: approvalBase({ status: 'REJECTED', decisionReason: 'Não encaminhar agora', decidedAt: now }), });
    currentCampaign = { ...campaign, status: 'APPROVED', approvedAt: now };
    expect(await screen.findByText('Decisão desta solicitação')).toBeInTheDocument();
    expect(screen.getAllByText('Rejeitada').length).toBeGreaterThan(0);
    expect(screen.getByText('Não encaminhar agora')).toBeInTheDocument();
    const campaignStatus = screen.getByText('Status atual da campanha').parentElement;
    expect(within(campaignStatus as HTMLElement).getByText('Aprovada')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Abrir campanha' }).every(link => link.getAttribute('href') === '/campanhas/camp-1')).toBe(true);
  });

  it('Approval decidida sem motivo informa ausência e não mostra composer', async () => {
    setup({ approval: approvalBase({ status: 'APPROVED', decisionReason: null, decidedAt: now }) });
    expect(await screen.findByText('Sem motivo informado.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Aprovar' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Rejeitar' })).not.toBeInTheDocument();
  });

  it('Creative associado abre workspace especializado, carrega contexto separado e não consulta estrutura de Campaign ou mídia', async () => {
    setup({ approval: approvalBase({ type: 'CREATIVE', entityType: 'CREATIVE', entityId: 'creative-1', requestedPayload: { rendersMedia: false }, description: 'Snapshot histórico sem alterações.' }) });
    expect(await screen.findByText('APROVAÇÃO DE CRIATIVO')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Parafusadeira — campanha de teste' })).toBeInTheDocument();
    expect(screen.getAllByText('Em revisão').length).toBeGreaterThan(0);
    expect(screen.queryByText('Pronto para revisão')).not.toBeInTheDocument();
    expect(screen.getByText('Campanha aprovada')).toBeInTheDocument();
    expect(screen.getByText('Título atual')).toBeInTheDocument();
    expect(screen.getByText('Roteiro atual')).toBeInTheDocument();
    expect(screen.getByText((_text, element) => element?.tagName === 'PRE' && element.textContent === 'Snapshot histórico sem alterações.')).toBeInTheDocument();
    expect(screen.getAllByText('Aviso de afiliação')).toHaveLength(2);
    expect(screen.getByText('Use proteção.')).toBeInTheDocument();
    expect(screen.getByText('Melhor do mercado sem evidência')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Abrir criativo' }).every(link => link.getAttribute('href') === '/criativos/creative-1')).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/creatives/creative-1/readiness'))).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/campaigns/camp-1'))).toBe(true);
    for (const forbidden of ['/channels', '/angles', '/experiments', '/media', 'instagram-publish']) expect(fetchMock.mock.calls.some(([url]) => String(url).includes(forbidden))).toBe(false);
    expect(screen.queryByRole('button', { name: /render/i })).not.toBeInTheDocument();
  });

  it('Creative pending confirma decisão, envia reason uma vez e não renderiza nem publica', async () => {
    setup({ approval: approvalBase({ type: 'CREATIVE', entityType: 'CREATIVE', entityId: 'creative-1' }) });
    fireEvent.change(await screen.findByLabelText('Motivo da decisão (opcional)'), { target: { value: 'Revisado por operador' } });
    fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }));
    expect(screen.getByText('Confirmar aprovação deste criativo?')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar aprovação' }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/approve') && init?.method === 'POST')).toHaveLength(1));
    const call = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith('/approve') && init?.method === 'POST');
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ reason: 'Revisado por operador' });
    expect(await screen.findByText('Criativo aprovado. Nenhuma renderização de mídia ou publicação foi executada.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Motivo da decisão (opcional)')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/creatives/from-'))).toBe(false);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('instagram-publish') || String(url).includes('/media/jobs'))).toBe(false);
  });

  it('Creative readiness blockers bloqueiam aprovação, não rejeição; warnings sem blockers permitem aprovar', async () => {
    setup({ approval: approvalBase({ type: 'CREATIVE', entityType: 'CREATIVE', entityId: 'creative-1' }), creativeReadiness: { state: 'NOT_READY', creativeStatus: 'READY_FOR_REVIEW', checks: {}, sceneCount: 2, blockers: [{ code: 'CREATIVE_NOT_READY', message: 'Defina o CTA.', field: 'cta' }], warnings: [{ code: 'LEGACY', message: 'Aviso não bloqueante.' }], compliance: { status: 'BLOCK', reasons: [], requiredWarningCoverage: [] } } });
    expect(await screen.findByText('Defina o CTA.')).toBeInTheDocument();
    expect(screen.getByText('Avisos — não bloqueiam a decisão')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Aprovar' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Rejeitar' })).toBeEnabled();
    expect(screen.getAllByRole('link', { name: 'Abrir criativo' }).every(link => link.getAttribute('href') === '/criativos/creative-1')).toBe(true);
  });

  it('warnings sem blockers não impedem aprovação de Creative', async () => {
    setup({ approval: approvalBase({ type: 'CREATIVE', entityType: 'CREATIVE', entityId: 'creative-1' }), creativeReadiness: { state: 'READY_FOR_REVIEW', creativeStatus: 'READY_FOR_REVIEW', checks: {}, sceneCount: 2, blockers: [], warnings: [{ code: 'LEGACY', message: 'Aviso permitido.' }], compliance: { status: 'PASS', reasons: [], requiredWarningCoverage: [] } } });
    expect(await screen.findByText('Aviso permitido.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Aprovar' })).toBeEnabled();
  });

  it('CREATIVE_APPROVAL_INVALIDATED atualiza aprovação, Creative, readiness e Campaign e mantém decisão pendente', async () => {
    setup({ approval: approvalBase({ type: 'CREATIVE', entityType: 'CREATIVE', entityId: 'creative-1' }), decisionFailure: 'CREATIVE_APPROVAL_INVALIDATED' });
    fireEvent.click(await screen.findByRole('button', { name: 'Aprovar' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar aprovação' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('O criativo mudou desde o envio e precisa ser revisado antes da aprovação.');
    expect(await screen.findByText('O conteúdo do criativo mudou.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Aprovar' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Rejeitar' })).toBeEnabled();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/approvals/approval-1')).length).toBeGreaterThan(1);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/creatives/creative-1')).length).toBeGreaterThan(1);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/creatives/creative-1/readiness')).length).toBeGreaterThan(1);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/campaigns/camp-1')).length).toBeGreaterThan(1);
  });

  it('conflito de decisão Creative recarrega Approval e remove o composer quando outra sessão decidiu', async () => {
    setup({ approval: approvalBase({ type: 'CREATIVE', entityType: 'CREATIVE', entityId: 'creative-1' }), decisionFailure: 'APPROVAL_DECISION_CONFLICT' });
    fireEvent.click(await screen.findByRole('button', { name: 'Rejeitar' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar rejeição' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Esta solicitação já foi decidida em outra sessão.');
    expect(await screen.findByText('Decisão desta solicitação')).toBeInTheDocument();
    expect(screen.queryByLabelText('Motivo da decisão (opcional)')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/creatives/creative-1/readiness')).length).toBeGreaterThan(1);
  });

  it('estado inconsistente do backend não cria outra Approval e orienta atualização', async () => {
    setup({ approval: approvalBase({ type: 'CREATIVE', entityType: 'CREATIVE', entityId: 'creative-1' }), decisionFailure: 'CREATIVE_APPROVAL_STATE_INCONSISTENT' });
    fireEvent.click(await screen.findByRole('button', { name: 'Aprovar' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar aprovação' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('O estado desta aprovação está inconsistente. Atualize os dados');
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).includes('/submit-for-review') && init?.method === 'POST')).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).includes('/approvals') && init?.method === 'POST')).toHaveLength(1);
  });

  it('decisão Creative rejeitada mostra motivo persistido e permite retornar ao Creative para correção', async () => {
    setup({ approval: approvalBase({ type: 'CREATIVE', entityType: 'CREATIVE', entityId: 'creative-1', status: 'REJECTED', decisionReason: 'Corrigir advertência.', decidedAt: now }) });
    expect(await screen.findByText('Criativo rejeitado. O conteúdo pode ser corrigido e enviado novamente para revisão.')).toBeInTheDocument();
    expect(screen.getByText('Corrigir advertência.')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Abrir criativo' }).every(link => link.getAttribute('href') === '/criativos/creative-1')).toBe(true);
    expect(screen.queryByRole('button', { name: 'Aprovar' })).not.toBeInTheDocument();
  });
});

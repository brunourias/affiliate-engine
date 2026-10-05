import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import type { Approval, CommercialBinding } from '../types';

const now = '2026-09-13T12:00:00Z';
let automationEnabled = true;
let goalCents = 100000;
let commercialBinding: CommercialBinding = { candidateId:'cc1', catalogProductId:'MLB1', sourceItemId:null, originalUrl:null, validationStatus:'NOT_SET', validationReasonCode:null, catalogMatchStatus:'UNKNOWN', observed:{}, affiliate:{status:'NOT_SET',urlPresent:false} };
let approvals: Approval[] = [
  { id: 'a1', type: 'STRATEGIC', status: 'PENDING', title: 'Decisão estratégica', description: 'Descrição', entityType: null, entityId: null, requestedPayload: null, decidedAt: null, decisionReason: null, createdAt: now, updatedAt: now },
  { id: 'a2', type: 'FINANCIAL', status: 'PENDING', title: 'Decisão financeira', description: 'Descrição', entityType: null, entityId: null, requestedPayload: null, decidedAt: null, decisionReason: null, createdAt: now, updatedAt: now },
  { id: 'a3', type: 'STRATEGIC', status: 'REJECTED', title: 'Decisão histórica', description: 'Resumo auditável', entityType: null, entityId: null, requestedPayload: null, decidedAt: now, decisionReason: null, createdAt: now, updatedAt: now },
];
const tasks = [
  { id: 't1', type: 'SYSTEM_HEARTBEAT', status: 'COMPLETED', title: 'Tarefa manual', payload: null, result: {}, error: null, isAutomatic: false, createdAt: now, startedAt: now, finishedAt: now, updatedAt: now },
  { id: 't2', type: 'SYSTEM_HEARTBEAT', status: 'PENDING', title: 'Tarefa automática', payload: null, result: null, error: null, isAutomatic: true, createdAt: now, startedAt: null, finishedAt: null, updatedAt: now },
];
const marketplace = { id: 'm1', provider: 'MERCADO_LIVRE', siteId: 'MLB', status: 'DEGRADED', authMode: 'ANONYMOUS', externalAccountId: null, externalNickname: null, lastCheckedAt: now, lastSuccessAt: null, metadata: {}, createdAt: now, updatedAt: now };
const capabilities = [
  { id: 'c1', provider: 'MERCADO_LIVRE', capabilityKey: 'CATEGORIES', status: 'AVAILABLE', endpoint: '/sites/MLB/categories', httpMethod: 'GET', lastHttpStatus: 200, latencyMs: 20, reasonCode: 'HTTP_200', message: 'Capacidade oficial disponível.', metadata: {}, checkedAt: now },
  { id: 'c2', provider: 'MERCADO_LIVRE', capabilityKey: 'MARKETPLACE_SEARCH', status: 'FORBIDDEN', endpoint: '/sites/MLB/search', httpMethod: 'GET', lastHttpStatus: 403, latencyMs: 18, reasonCode: 'HTTP_403', message: 'O acesso não foi autorizado.', metadata: {}, checkedAt: now },
];
const radarStatus = { provider: 'MERCADO_LIVRE', siteId: 'MLB', status: 'AVAILABLE', capabilities: { SITE: 'AVAILABLE', CATEGORIES: 'AVAILABLE', TRENDS_GLOBAL: 'AVAILABLE', TRENDS_CATEGORY: 'AVAILABLE', HIGHLIGHTS_CATEGORY: 'AVAILABLE', MARKETPLACE_SEARCH: 'FORBIDDEN', ITEM_DETAILS: 'FORBIDDEN' } };
const radarCategories = [{ id: 'mc1', provider: 'MERCADO_LIVRE', siteId: 'MLB', externalCategoryId: 'MLB5672', name: 'Ferramentas', parentExternalCategoryId: null, sourceCapability: 'CATEGORIES', firstSeenAt: now, lastSeenAt: now }];
const radarRun = { id: 'r1', provider: 'MERCADO_LIVRE', siteId: 'MLB', triggerType: 'MANUAL', status: 'COMPLETED', requestedCategoryId: 'MLB5672', startedAt: now, finishedAt: '2026-09-13T12:00:01Z', sourcesRequested: ['TRENDS_GLOBAL', 'TRENDS_CATEGORY', 'HIGHLIGHTS_CATEGORY'], sourcesSucceeded: ['TRENDS_GLOBAL', 'TRENDS_CATEGORY', 'HIGHLIGHTS_CATEGORY'], sourcesFailed: [], discoveredCount: 4, errorSummary: null };
const radarSignals = [
  { id: 's1', radarRunId: 'r1', provider: 'MERCADO_LIVRE', siteId: 'MLB', sourceType: 'TREND_GLOBAL', sourceCapability: 'TRENDS_GLOBAL', categoryExternalId: null, entityType: 'QUERY', externalId: null, displayText: 'parafusadeira', rank: 1, sourcePayload: {}, observedAt: now },
  { id: 's2', radarRunId: 'r1', provider: 'MERCADO_LIVRE', siteId: 'MLB', sourceType: 'HIGHLIGHT_CATEGORY', sourceCapability: 'HIGHLIGHTS_CATEGORY', categoryExternalId: 'MLB5672', entityType: 'ITEM', externalId: 'MLB1', displayText: null, rank: 2, sourcePayload: {}, observedAt: now },
  { id: 's3', radarRunId: 'r1', provider: 'MERCADO_LIVRE', siteId: 'MLB', sourceType: 'HIGHLIGHT_CATEGORY', sourceCapability: 'HIGHLIGHTS_CATEGORY', categoryExternalId: 'MLB5672', entityType: 'PRODUCT', externalId: 'MLB2', displayText: null, rank: 3, sourcePayload: {}, observedAt: now },
  { id: 's4', radarRunId: 'r1', provider: 'MERCADO_LIVRE', siteId: 'MLB', sourceType: 'HIGHLIGHT_CATEGORY', sourceCapability: 'HIGHLIGHTS_CATEGORY', categoryExternalId: 'MLB5672', entityType: 'USER_PRODUCT', externalId: 'MLBU3', displayText: null, rank: 4, sourcePayload: {}, observedAt: now },
];
const candidate={id:'cc1',provider:'MERCADO_LIVRE',siteId:'MLB',sourceType:'RADAR_SIGNAL',sourceRadarSignalId:'s2',sourceRadarRunId:'r1',entityType:'ITEM',externalId:'MLB1',categoryExternalId:'MLB5672',workingTitle:null,sourceUrl:null,notes:null,status:'NEW',evidenceStatus:'INSUFFICIENT_EVIDENCE',evidenceLevel:'NONE',firstSeenAt:now,lastSeenAt:now,createdAt:now,updatedAt:now};
const curatorCandidates=[candidate,{...candidate,id:'cc2',externalId:'MLB2',workingTitle:'Parafusadeira verificada',status:'INVESTIGATING',evidenceStatus:'VERIFIED',evidenceLevel:'DATA_ANALYZED'},{...candidate,id:'cc3',externalId:'MLB3',workingTitle:'Produto com evidências',status:'READY_FOR_REVIEW',evidenceStatus:'SUFFICIENT_EVIDENCE',evidenceLevel:'COMMUNITY_VALIDATED'}];
const decisions=[{id:'d1',timestamp:now,actor:'OPERATOR',entityType:'CREATIVE',entityId:'cr1',action:'CREATIVE_APPROVED',reason:null,confidence:null,metadata:{}}];
const assessment={id:'as1',candidateId:'cc1',assessmentVersion:1,previousAssessmentId:null,evidenceStatus:'VERIFIED',evidenceLevel:'DATA_ANALYZED',trustGate:'BLOCK',trustReasons:[],trustWarnings:[{code:'LIMITATION',message:'Uso apenas doméstico.',evidenceIds:['e1']}],recommendationScore:92,recommendationCoveragePercent:80,recommendationLabel:'EXCELLENT',opportunityScore:98,opportunityCoveragePercent:45,priceVerdict:'GOOD_PRICE',priceToBuyCents:null,editorialVerdict:'NOT_RECOMMENDED',recommendationPillars:{QUALITY_RELIABILITY:{status:'KNOWN',score:92,weight:25,weightedContribution:23,evidenceIds:['e1'],reasons:['Evidência verificada.']},ALTERNATIVES:{status:'UNKNOWN',score:null,weight:10,weightedContribution:null,evidenceIds:[],reasons:['Sem evidência.']}},opportunityPillars:{COMMISSION:{status:'UNKNOWN',score:null,weight:10,weightedContribution:null,evidenceIds:[],reasons:['Dado não disponível.']}},evidenceIdsUsed:['e1'],unknownFields:['COMMISSION'],rationale:{},evaluatedAt:now,createdAt:now};

const settings = () => ({ monthlyConfirmedCommissionGoalCents: goalCents, dailyPublicationLimit: 20, timezone: 'America/Sao_Paulo', systemAutomationEnabled: automationEnabled, radarEnabled: false, creativeEnabled: false, publishingEnabled: false, commentReplyEnabled: false, externalIntelligenceEnabled: false, updatedAt: now });
const dashboard = () => ({ settings: settings(), commission: { confirmedCents: 0, goalCents, sourceConnected: false }, agent: { status: automationEnabled ? 'AVAILABLE' : 'PAUSED', currentTask: null, pending: 1, failed: 0, lastExecution: null }, approvals: [], notifications: [], decisions, unreadNotifications: 0, pendingApprovals: 0 });

function response(body: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })); }

beforeEach(() => {
  automationEnabled = true; goalCents = 100000;
  commercialBinding = { candidateId:'cc1', catalogProductId:'MLB1', sourceItemId:null, originalUrl:null, validationStatus:'NOT_SET', validationReasonCode:null, catalogMatchStatus:'UNKNOWN', observed:{}, affiliate:{status:'NOT_SET',urlPresent:false} };
  approvals = approvals.map(item => ({ ...item, status: item.id === 'a3' ? 'REJECTED' : 'PENDING', decidedAt: item.id === 'a3' ? now : null }));
  vi.stubGlobal('prompt', vi.fn(() => 'motivo'));
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = String(input); const method = init?.method ?? 'GET';
    if (url.endsWith('/dashboard')) return response(dashboard());
    if (url.endsWith('/automation/pause')) { automationEnabled = false; return response(settings()); }
    if (url.endsWith('/automation/resume')) { automationEnabled = true; return response(settings()); }
    if (url.endsWith('/settings') && method === 'PATCH') { goalCents = JSON.parse(String(init?.body)).monthlyConfirmedCommissionGoalCents; return response(settings()); }
    if (url.endsWith('/settings')) return response(settings());
    if (url.endsWith('/creatives/cr1')) return response({ id:'cr1', campaignId:'cp1', name:'Criativo aprovado', status:'APPROVED', contentType:'VIDEO_SHORT', targetChannel:'TIKTOK' });
    if (url.endsWith('/campaigns/cp1')) return response({ id:'cp1', candidateId:'cc1', name:'Campanha de teste', status:'APPROVED' });
    if (url.endsWith('/creatives/cr1/scenes')) return response([]);
    if (url.includes('/creatives/cr1/media-handoff')) return response({ state:'READY_TO_CREATE', creativeId:'cr1', creativeStatus:'APPROVED', renderType:'PREVIEW', creativeApprovalId:'approval-1', inputFingerprint:'fingerprint', mediaJobId:null, mediaJobStatus:null, attemptNumber:1, previousMediaJobId:null, reasonCode:null, blockers:[], warnings:[] });
    if (url.endsWith('/media/diagnostics')) return response({ ffmpeg:{status:'AVAILABLE'}, ffprobe:{status:'AVAILABLE'}, tts:{status:'AVAILABLE'}, storage:{status:'AVAILABLE'} });
    if (url.includes('/media-jobs?') || url.includes('/media-assets?')) return response([]);
    if (url.includes('/product-media-bundles/')) return response({ ownerId:'cc1', assetCount:0, uniqueVisualGroups:0, videoCount:0, detailCount:0, heroCount:0, diversityScore:0, diversityLevel:'LOW', qualityCheck:'PASS', warning:null, assets:[] });
    if (url.includes('/distribution-plan')) return response({ recommendedSelection:[], recommendations:[], publicationCandidates:[], roles:{primary:null}, experimentId:null });
    if (url.endsWith('/approvals')) return response(approvals);
    if (url.endsWith('/decisions')) return response(decisions);
    if (url.includes('/approvals/') && method === 'POST') { const id = url.split('/').at(-2); const status = url.endsWith('/approve') ? 'APPROVED' : 'REJECTED'; approvals = approvals.map(item => item.id === id ? { ...item, status, decidedAt: now } : item); return response(approvals.find(item => item.id === id)); }
    if (url.endsWith('/tasks') && method === 'POST') return response(tasks[1], 201);
    if (url.endsWith('/tasks')) return response(tasks);
    if (url.endsWith('/health')) return response({ status: 'healthy', frontend: 'separate', backend: 'operational', database: 'operational', migrations: 'current', scheduler: 'operational', automationEnabled: true, futureIntegrations: 'not_configured', timestamp: now });
    if (url.endsWith('/marketplaces/mercado-livre/capabilities')) return response(capabilities);
    if (url.endsWith('/marketplaces/mercado-livre/diagnostics/item')) return response(marketplace);
    if (url.endsWith('/marketplaces/mercado-livre/diagnostics')) return response(marketplace);
    if (url.endsWith('/marketplaces/mercado-livre')) return response(marketplace);
    if (url.endsWith('/radar/mercado-livre/status')) return response(radarStatus);
    if (url.endsWith('/radar/mercado-livre/categories/sync')) return response({ fetched: 1, inserted: 1, updated: 0 });
    if (url.endsWith('/radar/mercado-livre/categories')) return response(radarCategories);
    if (url.endsWith('/radar/mercado-livre/runs/r1/resolve-products')) return response({ runId:'r1', signalsAvailable:1, signalsEligible:1, signalsProcessed:1, signalsSkippedByLimit:0, productsFoundRaw:3, productsSelected:3, selectedProducts:[], candidatesCreated:2, candidatesReused:1, evidenceAdded:6, candidateIds:['cc2','cc3'], failures:[], policyBlockedCount:0, policyBlocked:[] });
    if (url.endsWith('/radar/mercado-livre/runs/r1/triage')) return response({ runId:'r1', candidatesEvaluated:2, enrichmentLimit:10, topCandidates:[{candidateId:'cc2',title:'Produto',triageScore:82,triageStatus:'TRIAGE_HIGH',reasons:['HIGH_DISCOVERY_RELEVANCE'],markedForEnrichment:true}] });
    if (url.endsWith('/radar/mercado-livre/runs/r1/enrich')) return response({ runId:'r1', candidatesRequested:10, candidatesProcessed:10, candidatesEnriched:10, catalogAvailableCount:10, commercialEvidenceAvailableCount:0, candidatesWithoutBuyBox:10, evidenceAdded:0, evidenceChanged:0, evidenceUnchanged:0, priceAvailableCount:0, reviewsAvailableCount:0, sellerReputationAvailableCount:0, sourceSummary:{ catalog:{AVAILABLE:10,UNAVAILABLE:0,FORBIDDEN:0,FAILED:0}, buyBox:{AVAILABLE:0,UNAVAILABLE:10,FORBIDDEN:0,FAILED:0}, price:{AVAILABLE:0,UNAVAILABLE:10,FORBIDDEN:0,FAILED:0}, reviews:{AVAILABLE:0,UNAVAILABLE:10,FORBIDDEN:0,FAILED:0}, sellerReputation:{AVAILABLE:0,UNAVAILABLE:10,FORBIDDEN:0,FAILED:0} }, candidates:[] });
    if (url.endsWith('/radar/mercado-livre/runs/r1/signals')) return response(radarSignals);
    if (url.endsWith('/radar/mercado-livre/runs') && method === 'POST') return response(radarRun, 201);
    if (url.endsWith('/radar/mercado-livre/runs')) return response([radarRun]);
    if(url.endsWith('/curator/candidates'))return response(method==='POST'?candidate:curatorCandidates,method==='POST'?201:200);
    if(url.includes('/curator/candidates/from-radar/'))return response(candidate);
    if(url.endsWith('/curator/candidates/cc1/assessments'))return response([assessment]);
    if(url.endsWith('/curator/candidates/cc1/assess'))return response(assessment,201);
    if(url.endsWith('/curator/candidates/cc1/evidence'))return response([]);
    if(url.endsWith('/curator/candidates/cc1/commercial-binding/affiliate') && method === 'PATCH') { commercialBinding = { ...commercialBinding, affiliate:{status:'FORMAT_VALID',urlPresent:true,url:JSON.parse(String(init?.body)).affiliateUrl} }; return response(commercialBinding); }
    if(url.endsWith('/curator/candidates/cc1/commercial-binding') && method === 'POST') { commercialBinding = { ...commercialBinding, sourceItemId:JSON.parse(String(init?.body)).source, validationStatus:'VALIDATED', observed:{sellerId:42,price:129.9,currencyId:'BRL'} }; return response(commercialBinding); }
    if(url.endsWith('/curator/candidates/cc1/commercial-binding') && method === 'DELETE') { commercialBinding = { ...commercialBinding, sourceItemId:null, validationStatus:'NOT_SET', observed:{} }; return new Response(null, { status:204 }); }
    if(url.endsWith('/curator/candidates/cc1/commercial-binding'))return response(commercialBinding);
    if(url.endsWith('/curator/candidates/cc1/checklist'))return response({evidenceStatus:'INSUFFICIENT_EVIDENCE',evidenceLevel:'NONE',items:[{key:'IDENTITY',label:'Identidade',status:'AVAILABLE'},{key:'CURRENT_PRICE',label:'Preço atual',status:'MISSING'}]});
    if(url.endsWith('/curator/candidates/cc1'))return response(candidate);
    return response({});
  }));
});

afterEach(() => { vi.unstubAllGlobals(); });

async function renderAt(path: string) {
  window.history.pushState({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
  return render(<App />);
}

describe('Dashboard', () => {
  it('renderiza sem inventar comissão e apresenta labels em pt-BR', async () => {
    await renderAt('/');
    expect(await screen.findByText('Visão operacional')).toBeInTheDocument();
    expect(screen.getByText('Fonte de dados ainda não conectada')).toBeInTheDocument();
    expect(screen.getByText('R$ 0,00')).toBeInTheDocument();
    expect(screen.getByText('Disponível')).toBeInTheDocument();
    expect(screen.getByText('Executor local')).toBeInTheDocument();
  });

  it('traduz ações e entidades das últimas decisões', async () => {
    await renderAt('/');
    expect(await screen.findByText('Criativo aprovado')).toBeInTheDocument();
    expect(screen.getByText('Criativo')).toBeInTheDocument();
    expect(screen.queryByText('CREATIVE_APPROVED')).not.toBeInTheDocument();
  });

  it('pausa automação e atualiza o estado visual', async () => {
    await renderAt('/');
    fireEvent.click(await screen.findByRole('button', { name: 'Parar toda automação' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/automation/pause'), expect.objectContaining({ method: 'POST' })));
    expect(await screen.findByText('AUTOMAÇÃO PAUSADA')).toBeInTheDocument();
    expect(screen.getByText('Pausado')).toBeInTheDocument();
  });
});

describe('Workspace de produção de mídia', () => {
  it('a rota /criativos/:id/midia monta o workspace separado sem componentes ou chamadas de publicação', async () => {
    await renderAt('/criativos/cr1/midia');
    expect(await screen.findByRole('heading', { name: 'Criativo aprovado' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Próxima ação' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Preparar preview' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Preparar publicação' })).not.toBeInTheDocument();
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(([url]) => /publication-readiness|instagram-publish|media-delivery|publication-package|publication-executions/.test(String(url)))).toBe(false);
  });
});

describe('Registro de decisões', () => {
  it('usa os labels centrais para ação e tipo de entidade', async () => {
    await renderAt('/decisoes');
    expect(await screen.findByText('Criativo aprovado')).toBeInTheDocument();
    expect(screen.getByText('Criativo')).toBeInTheDocument();
    expect(screen.queryByText('CREATIVE_APPROVED')).not.toBeInTheDocument();
    expect(screen.queryByText(/^CREATIVE$/)).not.toBeInTheDocument();
  });
});

describe('Configurações', () => {
  it('carrega, altera e salva a meta mensal', async () => {
    await renderAt('/configuracoes');
    const input = await screen.findByLabelText('Meta mensal confirmada (R$)');
    fireEvent.change(input, { target: { value: '2500' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salvar alterações' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/settings'), expect.objectContaining({ method: 'PATCH', body: expect.stringContaining('250000') })));
    expect(input).toHaveValue(2500);
  });
});

describe('Aprovações', () => {
  it('renderiza a central com labels traduzidos e encaminha a solicitação pendente para revisão', async () => {
    await renderAt('/aprovacoes');
    expect((await screen.findAllByText('Estratégica')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Pendente').length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: 'Revisar' }).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Aprovar' })).not.toBeInTheDocument();
  });

  it('mostra acesso à decisão para solicitações já decididas', async () => {
    await renderAt('/aprovacoes');
    expect((await screen.findAllByText('Rejeitada')).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: 'Ver decisão' }).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Rejeitar' })).not.toBeInTheDocument();
  });
});

describe('Estados da aplicação', () => {
  it('mostra loading enquanto a API está pendente', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => undefined)));
    await renderAt('/');
    expect(screen.getByText('Carregando dados reais…')).toBeInTheDocument();
  });

  it('mostra erro e permite tentar novamente', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({ detail: 'Backend indisponível' }, 503)));
    await renderAt('/');
    expect(await screen.findByText('Não foi possível carregar.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Tentar novamente' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });
});

describe('Tarefas', () => {
  it('apresenta origem, tipo e status traduzidos', async () => {
    await renderAt('/tarefas');
    expect(await screen.findByText('Tarefa manual')).toBeInTheDocument();
    expect(screen.getByText('Manual')).toBeInTheDocument();
    expect(screen.getAllByText('Automática')).toHaveLength(2);
    expect(screen.getByText('Concluída')).toBeInTheDocument();
    expect(screen.getAllByText('Pendente').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Heartbeat do sistema').length).toBeGreaterThan(0);
  });

  it('envia isAutomatic=true ao criar tarefa automática', async () => {
    await renderAt('/tarefas');
    fireEvent.click(await screen.findByLabelText('Automática'));
    fireEvent.click(screen.getByRole('button', { name: 'Criar tarefa' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/tasks'), expect.objectContaining({ method: 'POST', body: expect.stringContaining('"isAutomatic":true') })));
  });
});

describe('Diagnóstico Mercado Livre', () => {
  it('exibe capacidades traduzidas e HTTP 403 sem quebrar', async () => {
    await renderAt('/sistema');
    expect(await screen.findByText('Categorias')).toBeInTheDocument();
    expect(screen.getByText('Disponível')).toBeInTheDocument();
    expect(screen.getByText('Proibida')).toBeInTheDocument();
    expect(screen.getByText('403')).toBeInTheDocument();
  });

  it('executa diagnóstico geral e mostra loading no botão', async () => {
    let resolveDiagnostic!: (value: Response) => void;
    const originalFetch = fetch as ReturnType<typeof vi.fn>;
    originalFetch.mockImplementationOnce(async (input: string | URL) => {
      const url = String(input);
      if (url.endsWith('/health')) return response({ status: 'healthy', frontend: 'separate', backend: 'operational', database: 'operational', migrations: 'current', scheduler: 'operational', automationEnabled: true, futureIntegrations: 'not_configured', timestamp: now });
      return response({});
    });
    await renderAt('/sistema');
    await screen.findAllByText('Mercado Livre');
    originalFetch.mockImplementation((input: string | URL) => String(input).endsWith('/diagnostics') ? new Promise(resolve => { resolveDiagnostic = resolve; }) : response(String(input).endsWith('/capabilities') ? capabilities : marketplace));
    fireEvent.click(screen.getByRole('button', { name: 'Testar capacidades' }));
    expect(await screen.findByRole('button', { name: 'Testando…' })).toBeDisabled();
    resolveDiagnostic(new Response(JSON.stringify(marketplace), { status: 200 }));
    await waitFor(() => expect(originalFetch).toHaveBeenCalledWith(expect.stringContaining('/diagnostics'), expect.objectContaining({ method: 'POST' })));
  });

  it('envia item informado e apresenta erro amigável', async () => {
    await renderAt('/sistema');
    const input = await screen.findByLabelText('URL ou item ID');
    fireEvent.change(input, { target: { value: 'MLB1234567890' } });
    fireEvent.click(screen.getByRole('button', { name: 'Testar item' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/diagnostics/item'), expect.objectContaining({ body: expect.stringContaining('MLB1234567890') })));
  });
});

describe('Radar', () => {
  it('renderiza status e limitações opcionais em pt-BR', async () => {
    await renderAt('/radar');
    expect(await screen.findByRole('heading', { name: 'Radar' })).toBeInTheDocument();
    expect(screen.getAllByText('Disponível').length).toBeGreaterThan(0);
    expect(screen.getByText(/busca geral Proibida/i)).toBeInTheDocument();
    expect(screen.getByText(/detalhes de item Proibida/i)).toBeInTheDocument();
  });

  it('sincroniza categorias', async () => {
    await renderAt('/radar');
    fireEvent.click(await screen.findByRole('button', { name: 'Sincronizar categorias' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/categories/sync'), expect.objectContaining({ method: 'POST' })));
  });

  it('seleciona categoria e executa o Radar', async () => {
    await renderAt('/radar');
    fireEvent.change(await screen.findByLabelText('Categoria do Radar'), { target: { value: 'MLB5672' } });
    fireEvent.click(screen.getByRole('button', { name: 'Executar Radar' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/radar/mercado-livre/runs'), expect.objectContaining({ method: 'POST', body: expect.stringContaining('MLB5672') })));
  });

  it('mostra sinais, tipos, posição e histórico', async () => {
    await renderAt('/radar');
    expect(await screen.findByText('parafusadeira')).toBeInTheDocument();
    expect(screen.getByText('Consulta')).toBeInTheDocument();
    expect(screen.getByText('Item')).toBeInTheDocument();
    expect(screen.getByText('Produto')).toBeInTheDocument();
    expect(screen.getByText('User Product')).toBeInTheDocument();
    expect(screen.getByText('#2')).toBeInTheDocument();
    expect(screen.getAllByText('4 sinais').length).toBeGreaterThan(0);
  });

  it('descobre produtos a partir de uma execução concluída sem executar o Radar novamente', async () => {
    await renderAt('/radar');
    fireEvent.click(await screen.findByRole('button', { name: 'Descobrir produtos' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/runs/r1/resolve-products'), expect.objectContaining({ method: 'POST' })));
    expect(await screen.findByText(/1 de 1 sinais elegíveis processados.*3 produtos selecionados de 3 encontrados.*2 novos/i)).toBeInTheDocument();
  });

  it('tria candidatos da execução concluída sem criar novos candidatos', async () => {
    await renderAt('/radar');
    fireEvent.click(await screen.findByRole('button', { name: 'Triar candidatos' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/runs/r1/triage'), expect.objectContaining({ method: 'POST' })));
    expect(await screen.findByText(/Top candidatos desta execução: 2 avaliados/i)).toBeInTheDocument();
  });

  it('diferencia catálogo disponível de evidência comercial ausente sem tratar a execução como erro', async () => {
    await renderAt('/radar');
    fireEvent.click(await screen.findByRole('button', { name: 'Enriquecer evidências' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/runs/r1/enrich'), expect.objectContaining({ method: 'POST' })));
    expect(await screen.findByText(/10 candidatos processados.*10 catálogos disponíveis.*0 com evidências comerciais.*10 sem buy box/i)).toBeInTheDocument();
    expect(screen.getByText('Nenhuma evidência comercial disponível nesta execução.')).toBeInTheDocument();
    expect(screen.queryByText(/10 candidatos enriquecidos/i)).not.toBeInTheDocument();
  });

  it('mostra estado vazio', async () => {
    vi.stubGlobal('fetch', vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.endsWith('/status')) return response(radarStatus);
      if (url.endsWith('/categories')) return response([]);
      if (url.endsWith('/runs')) return response([]);
      return response([]);
    }));
    await renderAt('/radar');
    expect(await screen.findByText('Nenhuma execução do Radar registrada.')).toBeInTheDocument();
    expect(screen.getByText('O histórico está vazio.')).toBeInTheDocument();
  });

  it('mostra loading inicial', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => undefined)));
    await renderAt('/radar');
    expect(screen.getByText('Carregando dados reais…')).toBeInTheDocument();
  });

  it('apresenta erro estruturado sem object Object', async () => {
    const baseFetch = fetch as ReturnType<typeof vi.fn>;
    await renderAt('/radar');
    await screen.findByRole('heading', { name: 'Radar' });
    baseFetch.mockImplementation((input: string | URL) => String(input).endsWith('/runs') ? response({ detail: [{ msg: 'Categoria inválida' }] }, 422) : response([]));
    fireEvent.click(screen.getByRole('button', { name: 'Executar Radar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Categoria inválida');
    expect(screen.queryByText('[object Object]')).not.toBeInTheDocument();
  });
});
describe('Curadoria',()=>{
  it('renderiza candidatos em cards traduzidos e preserva seus links',async()=>{await renderAt('/curator');expect(await screen.findByRole('heading',{name:'Curadoria'})).toBeInTheDocument();fireEvent.click(screen.getByRole('button',{name:'Todos os candidatos'}));expect(await screen.findByRole('heading',{name:'Todos os candidatos'})).toBeInTheDocument();expect(screen.getAllByText('Investigando').length).toBeGreaterThan(0);expect(screen.queryByText(/^INVESTIGATING$|^VERIFIED$|^SUFFICIENT_EVIDENCE$/)).not.toBeInTheDocument();expect(screen.getByRole('link',{name:/Parafusadeira verificada/})).toHaveAttribute('href','/curator/cc2');expect(screen.queryByText(/Recommendation Score|Opportunity Score/)).not.toBeInTheDocument()});
  it('mostra checklist, nível e estado vazio de evidências',async()=>{await renderAt('/curator/cc1');expect(await screen.findByText('Preço atual')).toBeInTheDocument();expect(screen.getByText('Nenhuma evidência registrada.')).toBeInTheDocument();expect(screen.getByRole('button',{name:'Avaliar candidato'})).toBeInTheDocument()});
  it('apresenta o candidato como painel de decisão e mantém detalhes técnicos recolhidos', async () => {
    await renderAt('/curator/cc1');
    expect(await screen.findByRole('heading', { name: 'Candidato em curadoria' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Da oportunidade à campanha' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ir para esta etapa' })).toHaveAttribute('href', '#candidate-opportunity');
    expect(screen.getByText('Identificadores e detalhes técnicos')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Vincular oferta' })).toBeInTheDocument();
    expect(screen.getByText('Aguardando decisão humana')).toBeInTheDocument();
  });
  it('mostra evidências oficiais sem inventar valores ausentes', async () => {
    const baseFetch = fetch as ReturnType<typeof vi.fn>;
    baseFetch.mockImplementation((input: string | URL) => {
      const url = String(input);
      if (url.endsWith('/curator/candidates/cc1/evidence')) return response([
        { id:'price-history', candidateId:'cc1', evidenceType:'CURRENT_PRICE', valueText:null, valueNumber:null, valueCents:99999, valueJson:{currency:'BRL'}, sourceKind:'OFFICIAL_API', sourceName:'Mercado Livre', sourceUrl:null, sourceReference:'MLB0', confidence:'HIGH', verificationStatus:'VERIFIED', observedAt:'2026-01-01T00:00:00Z', validUntil:'2026-01-02T00:00:00Z', isStale:false, metadata:{} },
        { id:'price-1', candidateId:'cc1', evidenceType:'CURRENT_PRICE', valueText:null, valueNumber:null, valueCents:12990, valueJson:{currency:'BRL'}, sourceKind:'OFFICIAL_API', sourceName:'Mercado Livre', sourceUrl:null, sourceReference:'MLB1', confidence:'HIGH', verificationStatus:'VERIFIED', observedAt:now, validUntil:null, isStale:false, metadata:{} },
        { id:'reviews-1', candidateId:'cc1', evidenceType:'REVIEW_SUMMARY', valueText:null, valueNumber:null, valueCents:null, valueJson:{ratingAverage:4.7,totalReviews:18}, sourceKind:'OFFICIAL_API', sourceName:'Mercado Livre', sourceUrl:null, sourceReference:'MLB1', confidence:'HIGH', verificationStatus:'VERIFIED', observedAt:now, validUntil:null, isStale:false, metadata:{} },
      ]);
      if (url.endsWith('/curator/candidates/cc1/checklist')) return response({ evidenceStatus:'INSUFFICIENT_EVIDENCE', evidenceLevel:'NONE', items:[] });
      if (url.endsWith('/curator/candidates/cc1/assessments')) return response([]);
      if (url.endsWith('/curator/candidates/cc1')) return response(candidate);
      return response({});
    });
    await renderAt('/curator/cc1');
    expect(await screen.findByText('Evidências oficiais')).toBeInTheDocument();
    const officialPanel = screen.getByText('Evidências oficiais').closest('section');
    expect(officialPanel).not.toBeNull();
    expect(within(officialPanel as HTMLElement).getByText(/129,90/)).toBeInTheDocument();
    expect(within(officialPanel as HTMLElement).queryByText(/999,99/)).not.toBeInTheDocument();
    expect(screen.getByText('4.7')).toBeInTheDocument();
    expect(screen.getByText('18')).toBeInTheDocument();
    expect(screen.getByText('Não disponível')).toBeInTheDocument();
  });
  it('explica assessment, UNKNOWN e precedência do BLOCK',async()=>{await renderAt('/curator/cc1');expect(await screen.findByText('Análise editorial')).toBeInTheDocument();expect(screen.getByText('Trust Gate')).toBeInTheDocument();expect(screen.getByText('Recommendation Score')).toBeInTheDocument();expect(screen.getByText('Cobertura: 80%')).toBeInTheDocument();expect(screen.getByText('92 / 100')).toBeInTheDocument();expect(screen.getByText('Não recomendado')).toBeInTheDocument();expect(screen.getAllByText('UNKNOWN').length).toBeGreaterThan(0);expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();expect(screen.queryByText(/BloqueadoTrust Gate/)).not.toBeInTheDocument();expect(screen.getByText('Uso apenas doméstico.')).toBeInTheDocument()});
  it('permite avaliar e exibe histórico',async()=>{await renderAt('/curator/cc1');fireEvent.click(await screen.findByRole('button',{name:'Avaliar candidato'}));await waitFor(()=>expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/assess'),expect.objectContaining({method:'POST'})));expect(screen.getByText('Histórico de análises')).toBeInTheDocument()});
  it('vincula oferta, preserva o catálogo e aceita link afiliado manual sem promessa de comissão', async () => {
    await renderAt('/curator/cc1');
    fireEvent.click(await screen.findByRole('button', { name:'Vincular oferta' }));
    fireEvent.change(screen.getByPlaceholderText(/Cole a URL ou informe o itemId/i), { target:{ value:'MLB22222222' } });
    fireEvent.click(screen.getByRole('button', { name:'Salvar oferta' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/commercial-binding'), expect.objectContaining({ method:'POST', body:expect.stringContaining('MLB22222222') })));
    expect(await screen.findByText('MLB22222222')).toBeInTheDocument();
    expect(screen.getAllByText('MLB1').length).toBeGreaterThan(1);
    fireEvent.click(screen.getByRole('button', { name:'Adicionar link de afiliado' }));
    fireEvent.change(screen.getByPlaceholderText('https://...'), { target:{ value:'https://affiliate.example/link' } });
    fireEvent.click(screen.getByRole('button', { name:'Salvar link afiliado' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/commercial-binding/affiliate'), expect.objectContaining({ method:'PATCH', body:expect.stringContaining('affiliate.example') })));
    expect(await screen.findByText('Adicionado')).toBeInTheDocument();
    expect(screen.queryByText(/comissão garantida/i)).not.toBeInTheDocument();
  });
  it('habilita enrichment para oferta explícita válida, não verificada ou sem status e bloqueia somente vínculo inválido', async () => {
    const states: CommercialBinding['validationStatus'][] = ['VALIDATED', 'UNVERIFIED', 'NOT_SET', 'INVALID'];
    for (const validationStatus of states) {
      commercialBinding = { ...commercialBinding, sourceItemId:'MLB4759377111', validationStatus,
        validationReasonCode: validationStatus === 'INVALID' ? 'NOT_FOUND' : validationStatus === 'UNVERIFIED' ? 'FORBIDDEN' : null };
      const view = await renderAt('/curator/cc1');
      const update = await screen.findByRole('button', { name:'Atualizar evidências' });
      if (validationStatus === 'INVALID') expect(update).toBeDisabled();
      else expect(update).toBeEnabled();
      if (validationStatus === 'UNVERIFIED') expect(screen.getByText('Não verificada')).toBeInTheDocument();
      view.unmount();
    }
    commercialBinding = { ...commercialBinding, sourceItemId:null, validationStatus:'NOT_SET', validationReasonCode:null };
    await renderAt('/curator/cc1');
    expect(await screen.findByRole('button', { name:'Atualizar evidências' })).toBeDisabled();
  });
  it('executa o enrichment individual da F2.5 para uma oferta explícita vinculada', async () => {
    commercialBinding = { ...commercialBinding, sourceItemId:'MLB4759377111', validationStatus:'UNVERIFIED', validationReasonCode:'FORBIDDEN' };
    await renderAt('/curator/cc1');
    fireEvent.click(await screen.findByRole('button', { name:'Atualizar evidências' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/curator/candidates/cc1/enrich'), expect.objectContaining({ method:'POST' })));
    expect(screen.queryByText(/erro/i)).not.toBeInTheDocument();
  });
  it('traduz URL somente de catálogo, mantém vínculo e não mostra confirmação de mismatch', async () => {
    commercialBinding = { ...commercialBinding, catalogProductId:'MLB73096308', sourceItemId:'MLB4759377111', validationStatus:'UNVERIFIED', validationReasonCode:'FORBIDDEN', catalogMatchStatus:'MATCHED' };
    await renderAt('/curator/cc1');
    fireEvent.click(await screen.findByRole('button', { name:'Alterar oferta' }));
    fireEvent.change(screen.getByPlaceholderText(/Cole a URL/i), { target:{ value:'https://www.mercadolivre.com.br/p/MLB73096308' } });
    const baseFetch = fetch as ReturnType<typeof vi.fn>;
    baseFetch.mockImplementation((input: string | URL, init?: RequestInit) => String(input).endsWith('/commercial-binding') && init?.method === 'POST' ? response({ detail:'CATALOG_PRODUCT_WITHOUT_OFFER' }, 422) : response({}));
    fireEvent.click(screen.getByRole('button', { name:'Salvar oferta' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Esta URL identifica um produto de catálogo');
    expect(screen.queryByText('CATALOG_PRODUCT_WITHOUT_OFFER')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Confirmo vínculo mesmo/i)).not.toBeInTheDocument();
    expect(screen.getByText('MLB4759377111')).toBeInTheDocument();
  });
  it('mostra confirmação apenas após mismatch real, não para matched ou oferta não verificada', async () => {
    commercialBinding = { ...commercialBinding, sourceItemId:'MLB4759377111', validationStatus:'VALIDATED', validationReasonCode:null, catalogMatchStatus:'MATCHED' };
    await renderAt('/curator/cc1');
    fireEvent.click(await screen.findByRole('button', { name:'Alterar oferta' }));
    expect(screen.queryByLabelText(/Confirmo vínculo mesmo/i)).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/Cole a URL/i), { target:{ value:'MLB99999999' } });
    const baseFetch = fetch as ReturnType<typeof vi.fn>;
    baseFetch.mockImplementation((input: string | URL, init?: RequestInit) => String(input).endsWith('/commercial-binding') && init?.method === 'POST' ? response({ detail:'CATALOG_PRODUCT_MISMATCH_CONFIRMATION_REQUIRED' }, 409) : response({}));
    fireEvent.click(screen.getByRole('button', { name:'Salvar oferta' }));
    expect(await screen.findByLabelText(/Confirmo vínculo mesmo/i)).toBeInTheDocument();
  });
  it('não mostra confirmação para uma oferta sem validação de catálogo', async () => {
    commercialBinding = { ...commercialBinding, sourceItemId:'MLB4759377111', validationStatus:'UNVERIFIED', validationReasonCode:'FORBIDDEN', catalogMatchStatus:'UNKNOWN' };
    await renderAt('/curator/cc1');
    fireEvent.click(await screen.findByRole('button', { name:'Alterar oferta' }));
    expect(screen.queryByLabelText(/Confirmo vínculo mesmo/i)).not.toBeInTheDocument();
  });
  it('remove o vínculo sem tratar DELETE como enrichment e atualiza a apresentação', async () => {
    commercialBinding = { ...commercialBinding, sourceItemId:'MLB849301960', validationStatus:'VALIDATED', validationReasonCode:null, catalogMatchStatus:'MATCHED', observed:{sellerId:44203679,price:149,currencyId:'BRL'} };
    await renderAt('/curator/cc1');
    fireEvent.click(await screen.findByRole('button', { name:'Remover vínculo' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/commercial-binding'), expect.objectContaining({ method:'DELETE' })));
    expect(await screen.findByText('Vínculo comercial removido.')).toBeInTheDocument();
    expect(screen.getByText('Nenhuma oferta vinculada')).toBeInTheDocument();
    expect(screen.queryByText(/Cannot read properties of undefined/i)).not.toBeInTheDocument();
  });
  it('mantém o vínculo visível e mostra erro amigável se a remoção falhar', async () => {
    commercialBinding = { ...commercialBinding, sourceItemId:'MLB849301960', validationStatus:'VALIDATED', validationReasonCode:null, catalogMatchStatus:'MATCHED' };
    await renderAt('/curator/cc1');
    const baseFetch = fetch as ReturnType<typeof vi.fn>;
    baseFetch.mockImplementation((input: string | URL, init?: RequestInit) => String(input).endsWith('/commercial-binding') && init?.method === 'DELETE' ? response({ detail:'Não foi possível remover o vínculo.' }, 500) : response({}));
    fireEvent.click(await screen.findByRole('button', { name:'Remover vínculo' }));
    expect(await screen.findByText('Não foi possível remover o vínculo.')).toBeInTheDocument();
    expect(screen.getByText('MLB849301960')).toBeInTheDocument();
  });
});

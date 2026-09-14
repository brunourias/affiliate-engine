import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import type { Approval } from '../types';

const now = '2026-09-13T12:00:00Z';
let automationEnabled = true;
let goalCents = 100000;
let approvals: Approval[] = [
  { id: 'a1', type: 'STRATEGIC', status: 'PENDING', title: 'Decisão estratégica', description: 'Descrição', entityType: null, entityId: null, requestedPayload: null, decidedAt: null, decisionReason: null, createdAt: now, updatedAt: now },
  { id: 'a2', type: 'FINANCIAL', status: 'PENDING', title: 'Decisão financeira', description: 'Descrição', entityType: null, entityId: null, requestedPayload: null, decidedAt: null, decisionReason: null, createdAt: now, updatedAt: now },
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

const settings = () => ({ monthlyConfirmedCommissionGoalCents: goalCents, dailyPublicationLimit: 20, timezone: 'America/Sao_Paulo', systemAutomationEnabled: automationEnabled, radarEnabled: false, creativeEnabled: false, publishingEnabled: false, commentReplyEnabled: false, externalIntelligenceEnabled: false, updatedAt: now });
const dashboard = () => ({ settings: settings(), commission: { confirmedCents: 0, goalCents, sourceConnected: false }, agent: { status: automationEnabled ? 'AVAILABLE' : 'PAUSED', currentTask: null, pending: 1, failed: 0, lastExecution: null }, approvals: [], notifications: [], decisions: [], unreadNotifications: 0, pendingApprovals: 0 });

function response(body: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })); }

beforeEach(() => {
  automationEnabled = true; goalCents = 100000;
  approvals = approvals.map(item => ({ ...item, status: 'PENDING', decidedAt: null }));
  vi.stubGlobal('prompt', vi.fn(() => 'motivo'));
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = String(input); const method = init?.method ?? 'GET';
    if (url.endsWith('/dashboard')) return response(dashboard());
    if (url.endsWith('/automation/pause')) { automationEnabled = false; return response(settings()); }
    if (url.endsWith('/automation/resume')) { automationEnabled = true; return response(settings()); }
    if (url.endsWith('/settings') && method === 'PATCH') { goalCents = JSON.parse(String(init?.body)).monthlyConfirmedCommissionGoalCents; return response(settings()); }
    if (url.endsWith('/settings')) return response(settings());
    if (url.endsWith('/approvals')) return response(approvals);
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
    if (url.endsWith('/radar/mercado-livre/runs/r1/signals')) return response(radarSignals);
    if (url.endsWith('/radar/mercado-livre/runs') && method === 'POST') return response(radarRun, 201);
    if (url.endsWith('/radar/mercado-livre/runs')) return response([radarRun]);
    if(url.endsWith('/curator/candidates'))return response(method==='POST'?candidate:[candidate],method==='POST'?201:200);
    if(url.includes('/curator/candidates/from-radar/'))return response(candidate);
    if(url.endsWith('/curator/candidates/cc1/evidence'))return response([]);
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

  it('pausa automação e atualiza o estado visual', async () => {
    await renderAt('/');
    fireEvent.click(await screen.findByRole('button', { name: 'Parar toda automação' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/automation/pause'), expect.objectContaining({ method: 'POST' })));
    expect(await screen.findByText('AUTOMAÇÃO PAUSADA')).toBeInTheDocument();
    expect(screen.getByText('Pausado')).toBeInTheDocument();
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
  it('renderiza e aprova uma solicitação com labels traduzidos', async () => {
    await renderAt('/aprovacoes');
    expect(await screen.findByText('Estratégica')).toBeInTheDocument();
    expect(screen.getAllByText('Pendente').length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole('button', { name: 'Aprovar' })[0]);
    expect(await screen.findByText('Aprovada')).toBeInTheDocument();
  });

  it('rejeita uma solicitação e traduz o estado', async () => {
    await renderAt('/aprovacoes');
    fireEvent.click((await screen.findAllByRole('button', { name: 'Rejeitar' }))[1]);
    expect(await screen.findByText('Rejeitada')).toBeInTheDocument();
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
  it('renderiza candidatos sem scores comerciais',async()=>{await renderAt('/curator');expect(await screen.findByRole('heading',{name:'Curadoria'})).toBeInTheDocument();expect(screen.getByText('Evidência insuficiente')).toBeInTheDocument();expect(screen.queryByText(/Recommendation Score|Opportunity Score/)).not.toBeInTheDocument()});
  it('mostra checklist, nível e estado vazio de evidências',async()=>{await renderAt('/curator/cc1');expect(await screen.findByText('Preço atual')).toBeInTheDocument();expect(screen.getByText('Nenhuma evidência registrada.')).toBeInTheDocument();expect(screen.getByText(/Pontuação disponível na próxima fase/)).toBeInTheDocument()});
});

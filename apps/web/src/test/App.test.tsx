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

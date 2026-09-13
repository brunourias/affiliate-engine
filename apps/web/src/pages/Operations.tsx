import { useCallback, useState } from 'react';
import { api } from '../api/client';
import { Badge, Empty, ErrorState, Loading, Section } from '../components/ui';
import { useLoad } from '../hooks';
import { date, label, statusTone } from '../lib/presentation';
import type { Approval, Decision, Notification } from '../types';

function Head({ eyebrow, title, desc }: { eyebrow: string; title: string; desc: string }) {
  return <header className="page-head"><div><span>{eyebrow}</span><h1>{title}</h1><p>{desc}</p></div></header>;
}

export function Approvals() {
  const loader = useCallback(() => api.approvals(), []);
  const { data, error, loading, refresh } = useLoad(loader);
  const [filter, setFilter] = useState('');
  const act = async (item: Approval, decision: 'approve' | 'reject') => {
    const reason = window.prompt('Motivo opcional da decisão:') ?? '';
    await api.decide(item.id, decision, reason); refresh();
  };
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} retry={refresh} />;
  const rows = (data ?? []).filter(x => !filter || x.status === filter);
  return <><Head eyebrow="GOVERNANÇA" title="Aprovações" desc="Decisões explícitas, persistidas e auditáveis." /><div className="toolbar"><select aria-label="Filtrar status" value={filter} onChange={e => setFilter(e.target.value)}><option value="">Todos os status</option><option value="PENDING">Pendente</option><option value="APPROVED">Aprovada</option><option value="REJECTED">Rejeitada</option></select></div><Section title={`${rows.length} solicitações`}><Table heads={['Solicitação', 'Tipo', 'Criada em', 'Status', 'Ações']} rows={rows.map(x => [<span><b>{x.title}</b><small>{x.description}</small></span>, label(x.type), date(x.createdAt), <Badge tone={statusTone(x.status)}>{label(x.status)}</Badge>, x.status === 'PENDING' ? <div className="actions"><button className="primary-button small" onClick={() => act(x, 'approve')}>Aprovar</button><button className="ghost-button small" onClick={() => act(x, 'reject')}>Rejeitar</button></div> : x.decisionReason ?? '—'])} /></Section></>;
}

export function Tasks() {
  const loader = useCallback(() => api.tasks(), []);
  const { data, error, loading, refresh } = useLoad(loader);
  const [type, setType] = useState('SYSTEM_HEARTBEAT');
  const [automatic, setAutomatic] = useState(false);
  const create = async () => { await api.createTask({ type, title: type === 'SYSTEM_HEARTBEAT' ? 'Heartbeat local' : 'Teste de falha controlada', isAutomatic: automatic }); refresh(); };
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} retry={refresh} />;
  return <><Head eyebrow="EXECUÇÃO LOCAL" title="Fila de tarefas" desc="Infraestrutura demonstrativa e segura de execução local; não é um agente de IA." /><Section title="Criar tarefa demonstrativa"><div className="inline-form"><select aria-label="Tipo da tarefa" value={type} onChange={e => setType(e.target.value)}><option value="SYSTEM_HEARTBEAT">Heartbeat do sistema</option><option value="CONTROLLED_FAILURE">Falha controlada</option></select><label><input type="checkbox" checked={automatic} onChange={e => setAutomatic(e.target.checked)} /> Automática</label><button className="primary-button" onClick={create}>Criar tarefa</button></div></Section><Section title={`${data?.length ?? 0} tarefas`}><Table heads={['Tarefa', 'Origem', 'Criada em', 'Status', 'Ações']} rows={(data ?? []).map(x => [<span><b>{x.title}</b><small>{label(x.type)}{x.error ? ` · ${x.error}` : ''}</small></span>, x.isAutomatic ? 'Automática' : 'Manual', date(x.createdAt), <Badge tone={statusTone(x.status)}>{label(x.status)}</Badge>, <div className="actions">{x.status === 'PENDING' && <><button className="primary-button small" onClick={async () => { try { await api.runTask(x.id); } catch (e) { alert((e as Error).message); } refresh(); }}>Executar</button><button className="ghost-button small" onClick={async () => { await api.cancelTask(x.id); refresh(); }}>Cancelar</button></>}</div>])} /></Section></>;
}

export function Notifications() {
  const loader = useCallback(() => api.notifications(), []);
  const { data, error, loading, refresh } = useLoad(loader);
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} retry={refresh} />;
  return <><Head eyebrow="CENTRAL INTERNA" title="Notificações" desc="Alertas operacionais e mudanças importantes do sistema." /><Section title={`${data?.filter(x => !x.isRead).length ?? 0} não lidas`} aside={<button className="ghost-button small" onClick={async () => { await api.readAll(); refresh(); }}>Marcar todas como lidas</button>}><div className="notice-list">{data?.length ? data.map((x: Notification) => <button key={x.id} className={x.isRead ? 'read' : ''} onClick={async () => { await api.read(x.id); refresh(); }}><i className={statusTone(x.severity)} /><span><b>{x.title}</b><small>{x.message}</small><em>{date(x.createdAt)}</em></span><Badge tone={statusTone(x.severity)}>{label(x.severity)}</Badge></button>) : <Empty>Nenhuma notificação.</Empty>}</div></Section></>;
}

export function Decisions() {
  const loader = useCallback(() => api.decisions(), []);
  const { data, error, loading, refresh } = useLoad(loader);
  const [actor, setActor] = useState('');
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} retry={refresh} />;
  const rows = (data ?? []).filter(x => !actor || x.actor === actor);
  return <><Head eyebrow="AUDITORIA" title="Registro de decisões" desc="Histórico append-only das decisões relevantes." /><div className="toolbar"><select aria-label="Filtrar ator" value={actor} onChange={e => setActor(e.target.value)}><option value="">Todos os atores</option><option value="OPERATOR">Operador</option><option value="SYSTEM">Sistema</option></select></div><Section title={`${rows.length} decisões`}><Table heads={['Data', 'Ação', 'Ator', 'Entidade', 'Detalhes']} rows={rows.map((x: Decision) => [date(x.timestamp), <b>{x.action}</b>, label(x.actor), x.entityType, <details><summary>Ver</summary><pre>{JSON.stringify(x.metadata, null, 2)}</pre>{x.reason}</details>])} /></Section></>;
}

function Table({ heads, rows }: { heads: string[]; rows: React.ReactNode[][] }) {
  return rows.length ? <div className="table-wrap"><table><thead><tr>{heads.map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody></table></div> : <Empty>Nenhum registro encontrado.</Empty>;
}

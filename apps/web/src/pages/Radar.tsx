import { useCallback, useState } from 'react';
import { api } from '../api/client';
import { Badge, Empty, ErrorState, Loading, Section } from '../components/ui';
import { useLoad } from '../hooks';
import { date, label, statusTone } from '../lib/presentation';
import type { RadarRun, RadarSignal } from '../types';

const SOURCE_LABELS = ['TRENDS_GLOBAL', 'TRENDS_CATEGORY', 'HIGHLIGHTS_CATEGORY'];

export function RadarPage() {
  const loader = useCallback(async () => {
    const [status, categories, runs] = await Promise.all([api.radarStatus(), api.radarCategories(), api.radarRuns()]);
    const signals = runs[0] ? await api.radarSignals(runs[0].id) : [];
    return { status, categories, runs, selectedRun: runs[0] ?? null, signals };
  }, []);
  const { data, error, loading, refresh } = useLoad(loader);
  const [category, setCategory] = useState('');
  const [busy, setBusy] = useState<'sync'|'run'|'history'|null>(null);
  const [actionError, setActionError] = useState<string|null>(null);
  const [selectedRun, setSelectedRun] = useState<RadarRun|null>(null);
  const [signals, setSignals] = useState<RadarSignal[]|null>(null);
  async function sync() { setBusy('sync'); setActionError(null); try { await api.syncRadarCategories(); await refresh(); } catch (reason) { setActionError(reason instanceof Error ? reason.message : 'Não foi possível sincronizar.'); } finally { setBusy(null); } }
  async function run() { setBusy('run'); setActionError(null); try { const created = await api.createRadarRun(category || null); const found = await api.radarSignals(created.id); setSelectedRun(created); setSignals(found); await refresh(); } catch (reason) { setActionError(reason instanceof Error ? reason.message : 'Não foi possível executar o Radar.'); } finally { setBusy(null); } }
  async function openRun(item: RadarRun) { setBusy('history'); setActionError(null); try { setSelectedRun(item); setSignals(await api.radarSignals(item.id)); } catch (reason) { setActionError(reason instanceof Error ? reason.message : 'Não foi possível abrir a execução.'); } finally { setBusy(null); } }
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Sem dados')} retry={refresh} />;
  const currentRun = selectedRun ?? data.selectedRun;
  const currentSignals = signals ?? data.signals;
  const categoryNames = Object.fromEntries(data.categories.map(item => [item.externalCategoryId, item.name]));
  return <><header className="page-head"><div><span>SINAIS OFICIAIS</span><h1>Radar</h1><p>Observe tendências e destaques do Mercado Livre sem scoring ou enriquecimento artificial.</p></div></header>
    <Section title="Status do Radar"><div className="connection-grid"><div><small>Provider</small><b>Mercado Livre</b></div><div><small>Site</small><b>{data.status.siteId}</b></div><div><small>Status</small><Badge tone={statusTone(data.status.status)}>{label(data.status.status)}</Badge></div></div><div className="source-status">{SOURCE_LABELS.map(key => <span key={key}>{label(key)} <Badge tone={statusTone(data.status.capabilities[key] ?? 'UNKNOWN')}>{label(data.status.capabilities[key] ?? 'UNKNOWN')}</Badge></span>)}</div><p className="timestamp">Limitações conhecidas: busca geral {label(data.status.capabilities.MARKETPLACE_SEARCH ?? 'UNKNOWN')} · detalhes de item {label(data.status.capabilities.ITEM_DETAILS ?? 'UNKNOWN')}. Essas capacidades são opcionais para o Radar.</p></Section>
    <Section title="Executar Radar"><div className="diagnostic-controls"><label>Categoria<select aria-label="Categoria do Radar" value={category} onChange={event => setCategory(event.target.value)}><option value="">Somente tendências gerais</option>{data.categories.map(item => <option key={item.id} value={item.externalCategoryId}>{item.name} ({item.externalCategoryId})</option>)}</select></label><button className="primary-button" disabled={busy !== null} onClick={run}>{busy === 'run' ? 'Executando…' : 'Executar Radar'}</button><button className="ghost-button" disabled={busy !== null} onClick={sync}>{busy === 'sync' ? 'Sincronizando…' : 'Sincronizar categorias'}</button></div>{data.categories.length === 0 && <p className="timestamp">Sincronize as categorias para executar fontes por categoria.</p>}{actionError && <p className="inline-error" role="alert">{actionError}</p>}</Section>
    <Section title="Resultado selecionado">{currentRun ? <RunSummary run={currentRun} categoryName={currentRun.requestedCategoryId ? categoryNames[currentRun.requestedCategoryId] : null} /> : <Empty>Nenhuma execução do Radar registrada.</Empty>}</Section>
    <Section title="Sinais encontrados">{busy === 'history' ? <Loading /> : currentSignals.length ? <div className="table-wrap"><table><thead><tr><th>Fonte</th><th>Posição</th><th>Sinal / termo</th><th>Tipo</th><th>ID externo</th><th>Categoria</th><th>Observado em</th><th>Ação</th></tr></thead><tbody>{currentSignals.map(item => <tr key={item.id}><td>{label(item.sourceType)}</td><td>{item.rank ? `#${item.rank}` : '—'}</td><td>{item.displayText ?? '—'}</td><td>{label(item.entityType)}</td><td>{item.externalId ?? '—'}</td><td>{item.categoryExternalId ? categoryNames[item.categoryExternalId] ?? item.categoryExternalId : '—'}</td><td>{date(item.observedAt)}</td><td><button onClick={async()=>{const c=await api.investigate(item.id);window.location.assign('/curator/'+c.id)}}>Investigar</button></td></tr>)}</tbody></table></div> : <Empty>Nenhum sinal encontrado nesta execução.</Empty>}</Section>
    <Section title="Histórico de execuções">{data.runs.length ? <div className="compact-list run-history">{data.runs.map(item => <button key={item.id} onClick={() => openRun(item)}><span><b>{date(item.startedAt)}</b><small>{item.requestedCategoryId ? categoryNames[item.requestedCategoryId] ?? item.requestedCategoryId : 'Tendências gerais'}</small></span><Badge tone={statusTone(item.status)}>{label(item.status)}</Badge><strong>{item.discoveredCount} sinais</strong></button>)}</div> : <Empty>O histórico está vazio.</Empty>}</Section></>;
}

function RunSummary({ run, categoryName }: { run: RadarRun; categoryName: string|null|undefined }) {
  const duration = run.finishedAt ? Math.max(0, new Date(run.finishedAt).getTime() - new Date(run.startedAt).getTime()) : null;
  return <div className="run-summary"><div><small>Status</small><Badge tone={statusTone(run.status)}>{label(run.status)}</Badge></div><div><small>Horário</small><b>{date(run.startedAt)}</b></div><div><small>Fontes concluídas</small><b>{run.sourcesSucceeded.map(label).join(', ') || 'Nenhuma'}</b></div><div><small>Sinais</small><b>{run.discoveredCount}</b></div><div><small>Categoria</small><b>{categoryName ?? run.requestedCategoryId ?? 'Não informada'}</b></div><div><small>Duração</small><b>{duration === null ? 'Em execução' : `${duration} ms`}</b></div></div>;
}

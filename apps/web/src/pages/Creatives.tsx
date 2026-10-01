import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { creativesApi } from '../api/creatives';
import { Badge, Empty, ErrorState, Loading, Section } from '../components/ui';
import { useLoad } from '../hooks';
import { creativeStatusLabel, label, statusTone } from '../lib/presentation';
import { CreativeWorkspace } from './CreativeWorkspace';

export function CreativesPage() {
  const load = useCallback(() => creativesApi.list(), []);
  const { data, error, loading, refresh } = useLoad(load);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Erro')} retry={refresh} />;
  const count = (status: string) => data.filter((creative) => creative.status === status).length;

  return <>
    <header className="page-head"><div><span>ESTÚDIO DE CRIATIVOS</span><h1>Criativos</h1><p>Estruturas textuais aprovadas antes de qualquer renderização.</p></div></header>
    <div className="metric-grid">{[['DRAFT', 'Rascunhos'], ['READY_FOR_REVIEW', 'Em revisão'], ['APPROVED', 'Aprovados'], ['REJECTED', 'Rejeitados']].map(([status, title]) => <div key={status}><b>{count(status)}</b><span>{title}</span></div>)}</div>
    <Section title="Criativos">{data.length ? <div className="compact-list">{data.map((creative) => <Link key={creative.id} to={`/criativos/${creative.id}`}><span><b>{creative.name}</b><small>{label(creative.contentType)} · {label(creative.targetChannel)} · {creative.hook || 'Hook pendente'}</small></span><Badge tone={statusTone(creative.status)}>{creativeStatusLabel(creative.status)}</Badge></Link>)}</div> : <Empty>Nenhum criativo criado.</Empty>}</Section>
  </>;
}

export function CreativePage() {
  return <CreativeWorkspace />;
}

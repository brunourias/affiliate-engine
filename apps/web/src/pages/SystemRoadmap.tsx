import { useCallback } from 'react';
import { CheckCircle2, LockKeyhole } from 'lucide-react';
import { api } from '../api/client';
import { Badge, ErrorState, Loading, Section } from '../components/ui';
import { MercadoLivrePanel } from '../components/MercadoLivrePanel';
import { useLoad } from '../hooks';
import { date, label, statusTone } from '../lib/presentation';

export function SystemPage() {
  const loader = useCallback(() => api.health(), []);
  const { data, error, loading, refresh } = useLoad(loader);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Sem dados')} retry={refresh} />;
  const items = [['Frontend', 'operational'], ['Backend', data.backend], ['Banco', data.database], ['Migrations', data.migrations], ['Scheduler', data.scheduler], ['Automação global', data.automationEnabled ? 'Ativa' : 'Pausada']];
  return <><header className="page-head"><div><span>DIAGNÓSTICO LOCAL</span><h1>Sistema</h1><p>Estado da infraestrutura e das capacidades oficiais configuradas.</p></div><button className="ghost-button" onClick={refresh}>Atualizar status</button></header><Section title="Saúde do sistema"><div className="health-grid">{items.map(([name, value]) => <div key={name}><CheckCircle2 /><span><b>{name}</b><small>{label(value)}</small></span><Badge tone={statusTone(value)}>{value === 'Pausada' ? 'ATENÇÃO' : 'OK'}</Badge></div>)}</div><p className="timestamp">Última resposta: {date(data.timestamp)}</p></Section><Section title="Segurança local"><div className="security"><LockKeyhole /><div><b>Somente loopback</b><p>Backend e frontend são iniciados em 127.0.0.1. CORS aceita apenas origens locais explicitamente configuradas.</p></div></div></Section><MercadoLivrePanel /></>;
}

const phases = [['V1-A', 'Foundation + Control Center', 'HOMOLOGADA'], ['V1-B.1', 'Conexão + diagnóstico de capacidades', 'HOMOLOGADA'], ['V1-B.2', 'Mercado Livre Radar', 'ATUAL · EM HOMOLOGAÇÃO'], ['V1-C', 'Curator Engine', 'PRÓXIMA'], ['V1-D', 'Campaign Engine', 'PLANEJADO'], ['V1-E', 'Creative Studio', 'PLANEJADO'], ['V1-F', 'Video Pipeline', 'PLANEJADO'], ['V1-G', 'Social Publishers', 'PLANEJADO'], ['V1-H', 'Analytics', 'PLANEJADO'], ['V1-I', 'Learning Engine + Agent Chat', 'PLANEJADO'], ['V1-J', 'External Intelligence', 'PLANEJADO']];

export function Roadmap() {
  return <><header className="page-head"><div><span>EVOLUÇÃO DO PRODUTO</span><h1>Roadmap</h1><p>O que existe agora e o que permanece deliberadamente fora do banco e da interface.</p></div></header><Section title="Fases"><div className="timeline">{phases.map(([id, title, status], index) => <div className={index === 2 ? 'current' : ''} key={id}><i>{id}</i><span><b>{title}</b><small>{status}</small></span></div>)}</div></Section><Section title="Módulos futuros"><div className="future-grid">{['Produtos enriquecidos', 'Preços', 'Campanhas', 'Criativos', 'Publicações', 'Analytics', 'Inteligência', 'Audiência própria'].map(item => <div key={item}><LockKeyhole /><b>{item}</b><span>Não implementado na V1-B.2</span></div>)}</div></Section></>;
}

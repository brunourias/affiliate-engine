import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { ErrorState, Loading, Section } from '../components/ui';
import { useLoad } from '../hooks';
import type { Settings } from '../types';

export function SettingsPage() {
  const loader = useCallback(() => api.settings(), []);
  const { data, error, loading, refresh } = useLoad(loader);
  const [form, setForm] = useState<Settings | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => setForm(data), [data]);
  if (loading || !form) return <Loading />;
  if (error) return <ErrorState error={error} retry={refresh} />;
  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => setForm({ ...form, [key]: value });
  const save = async () => { await api.patchSettings(form); setSaved(true); setTimeout(() => setSaved(false), 2000); refresh(); };
  const toggles = [
    ['systemAutomationEnabled', 'Automação global', 'Controla o início de tarefas automáticas.'],
    ['radarEnabled', 'Radar', 'Intenção futura; integração não implementada.'],
    ['creativeEnabled', 'Criação de conteúdo', 'Intenção futura; geração não implementada.'],
    ['publishingEnabled', 'Publicação', 'Intenção futura; publicação não implementada.'],
    ['commentReplyEnabled', 'Comentários automáticos', 'Intenção futura; respostas não implementadas.'],
    ['externalIntelligenceEnabled', 'Inteligência externa', 'Intenção futura; coleta não implementada.'],
  ] as const;
  return <><header className="page-head"><div><span>PREFERÊNCIAS OPERACIONAIS</span><h1>Configurações</h1><p>Limites globais e intenção dos módulos futuros.</p></div></header><Section title="Metas e limites"><div className="form-grid"><label>Meta mensal confirmada (R$)<input type="number" min="0" step="0.01" value={form.monthlyConfirmedCommissionGoalCents / 100} onChange={e => set('monthlyConfirmedCommissionGoalCents', Math.round(Number(e.target.value) * 100))} /></label><label>Limite diário de publicações<input type="number" min="0" value={form.dailyPublicationLimit} onChange={e => set('dailyPublicationLimit', Number(e.target.value))} /></label><label>Fuso horário<input value={form.timezone} onChange={e => set('timezone', e.target.value)} /></label></div></Section><Section title="Automação e módulos"><div className="switch-list">{toggles.map(([key, title, description]) => <label key={key}><span><b>{title}</b><small>{description}</small></span><input type="checkbox" role="switch" checked={form[key]} onChange={e => set(key, e.target.checked)} /></label>)}</div></Section><div className="savebar"><span>{saved ? 'Configurações salvas e registradas no Registro de decisões.' : ''}</span><button className="primary-button" onClick={save}>Salvar alterações</button></div></>;
}

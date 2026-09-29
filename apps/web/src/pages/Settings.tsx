import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { ErrorState, Loading, Section } from '../components/ui';
import { useLoad } from '../hooks';
import type { Settings } from '../types';

export function SettingsPage() {
  const loader = useCallback(async () => ({ settings: await api.settings(), categories: await api.radarCategories() }), []);
  const { data, error, loading, refresh } = useLoad(loader);
  const [form, setForm] = useState<Settings | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => setForm(data?.settings ?? null), [data]);
  if (loading || !form) return <Loading />;
  if (error) return <ErrorState error={error} retry={refresh} />;
  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => setForm({ ...form, [key]: value });
  const save = async () => { await api.patchSettings(form); setSaved(true); setTimeout(() => setSaved(false), 2000); refresh(); };
  const toggles = [
    ['systemAutomationEnabled', 'Automação global', 'Controla o início de tarefas automáticas.'],
    ['radarEnabled', 'Radar', 'Permite execuções manuais com as fontes oficiais disponíveis.'],
    ['creativeEnabled', 'Criação de conteúdo', 'Intenção futura; geração não implementada.'],
    ['publishingEnabled', 'Publicação', 'Intenção futura; publicação não implementada.'],
    ['commentReplyEnabled', 'Comentários automáticos', 'Intenção futura; respostas não implementadas.'],
    ['externalIntelligenceEnabled', 'Inteligência externa', 'Intenção futura; coleta não implementada.'],
  ] as const;
  const categories=data!.categories; const preferred=form.preferredMarketplaceCategoryIds ?? []; const selected=new Set(preferred); const toggleCategory=(id:string)=>set('preferredMarketplaceCategoryIds', selected.has(id)?preferred.filter(x=>x!==id):[...preferred,id]);
  return <><header className="page-head"><div><span>PREFERÊNCIAS OPERACIONAIS</span><h1>Configurações</h1><p>Limites globais e ativação explícita dos módulos disponíveis.</p></div></header><Section title="Metas e limites"><div className="form-grid"><label>Meta mensal confirmada (R$)<input type="number" min="0" step="0.01" value={form.monthlyConfirmedCommissionGoalCents / 100} onChange={e => set('monthlyConfirmedCommissionGoalCents', Math.round(Number(e.target.value) * 100))} /></label><label>Limite diário de publicações<input type="number" min="0" value={form.dailyPublicationLimit} onChange={e => set('dailyPublicationLimit', Number(e.target.value))} /></label><label>Fuso horário<input value={form.timezone} onChange={e => set('timezone', e.target.value)} /></label></div></Section><Section title="Categorias de interesse">{categories.length?<><p>{preferred.length} categorias selecionadas</p><div className="switch-list">{categories.map(item=><label key={item.id}><span><b>{item.name}</b><small>{item.externalCategoryId}</small></span><input type="checkbox" checked={selected.has(item.externalCategoryId)} onChange={()=>toggleCategory(item.externalCategoryId)}/></label>)}</div><label><input type="checkbox" checked={form.includeGlobalTrendsOutsidePreferredCategories ?? false} onChange={e=>set('includeGlobalTrendsOutsidePreferredCategories',e.target.checked)}/> Considerar tendências globais fora das categorias selecionadas</label></>:<p>Sincronize as categorias do Mercado Livre no Radar antes de configurar.</p>}</Section><Section title="Automação e módulos"><div className="switch-list">{toggles.map(([key, title, description]) => <label key={key}><span><b>{title}</b><small>{description}</small></span><input type="checkbox" role="switch" checked={form[key]} onChange={e => set(key, e.target.checked)} /></label>)}</div></Section><div className="savebar"><span>{saved ? 'Configurações salvas e registradas no Registro de decisões.' : ''}</span><button className="primary-button" onClick={save}>Salvar alterações</button></div></>;
}

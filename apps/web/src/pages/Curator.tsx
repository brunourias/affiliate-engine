import { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { Badge, Empty, ErrorState, Loading, Section } from '../components/ui';
import { AssessmentPanel } from '../components/AssessmentPanel';
import { useLoad } from '../hooks';
import { date, label, statusTone } from '../lib/presentation';
import type { Evidence } from '../types';

function officialEvidence(evidence: Evidence[], type: string) {
  return evidence.filter(item => item.evidenceType === type && !item.isStale).sort((left, right) => right.observedAt.localeCompare(left.observedAt))[0];
}
function unavailable(value: unknown) { return value === null || value === undefined || value === '' ? 'Não disponível' : String(value); }
function formatPrice(evidence?: Evidence) {
  if (!evidence || evidence.valueCents === null || evidence.valueCents === undefined) return 'Não disponível';
  const metadata = (evidence.valueJson ?? {}) as Record<string, unknown>;
  const currency = typeof metadata.currency === 'string' ? metadata.currency : 'BRL';
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency }).format(evidence.valueCents / 100);
}

export function CuratorPage() {
  const navigate = useNavigate();
  const load = useCallback(() => api.candidates(), []);
  const { data, error, loading, refresh } = useLoad(load);
  const [formVisible, setFormVisible] = useState(false);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Sem dados')} retry={refresh} />;
  const countStatus = (status: string) => data.filter(candidate => candidate.status === status).length;
  const ranked = [...data].sort((left, right) => (right.triageScore ?? -1) - (left.triageScore ?? -1) || left.id.localeCompare(right.id));
  return <>
    <header className="page-head"><div><span>INVESTIGAÇÃO EDITORIAL</span><h1>Curadoria</h1><p>Candidatos em investigação antes de qualquer recomendação.</p></div><button className="primary-button" onClick={() => setFormVisible(visible => !visible)}>+ Novo candidato</button></header>
    {formVisible && <Section title="Novo candidato"><form className="diagnostic-controls" onSubmit={async event => { event.preventDefault(); const fields = new FormData(event.currentTarget); const candidate = await api.createCandidate({ provider: fields.get('provider'), entityType: fields.get('entityType'), workingTitle: fields.get('title') || null, sourceUrl: fields.get('url') || null, notes: fields.get('notes') || null }); navigate(`/curator/${candidate.id}`); }}><select name="provider"><option value="OTHER">Outro</option><option value="MERCADO_LIVRE">Mercado Livre</option></select><select name="entityType"><option value="MANUAL">Manual</option><option value="ITEM">Item</option><option value="PRODUCT">Produto</option><option value="QUERY">Termo</option></select><input name="title" placeholder="Título de trabalho (opcional)" /><input name="url" placeholder="URL pública (opcional)" /><input name="notes" placeholder="Notas" /><button className="primary-button">Criar</button></form></Section>}
    <div className="metric-grid"><div><b>{countStatus('NEW')}</b><span>Novos</span></div><div><b>{countStatus('INVESTIGATING')}</b><span>Investigando</span></div><div><b>{data.filter(candidate => candidate.evidenceStatus === 'INSUFFICIENT_EVIDENCE').length}</b><span>Evidência insuficiente</span></div><div><b>{countStatus('READY_FOR_REVIEW')}</b><span>Prontos para revisão</span></div></div>
    <Section title="Candidatos">{ranked.length ? <div className="compact-list">{ranked.map(candidate => { const reasons = candidate.triageReasons ?? []; return <Link key={candidate.id} to={`/curator/${candidate.id}`}><span><b>{candidate.workingTitle || candidate.externalId || 'Candidato sem título'}</b><small>{label(candidate.sourceType)} · {label(candidate.entityType)} · {candidate.categoryExternalId || 'Sem categoria'}{candidate.triageScore !== null && candidate.triageScore !== undefined ? ` · Triagem ${candidate.triageScore}/100 · ${label(candidate.triageStatus ?? '')}` : ''}{reasons.length ? ` · ${reasons.slice(0, 2).map(label).join(', ')}` : ''}</small></span><Badge tone={statusTone(candidate.evidenceStatus)}>{label(candidate.evidenceStatus)}</Badge><strong>{label(candidate.status)}</strong></Link>; })}</div> : <Empty>Nenhum candidato em curadoria.</Empty>}</Section>
  </>;
}

export function CandidatePage() {
  const { id = '' } = useParams();
  const load = useCallback(async () => { const [candidate, evidence, checklist, assessments] = await Promise.all([api.candidate(id), api.evidence(id), api.checklist(id), api.assessments(id)]); return { candidate, evidence, checklist, assessments }; }, [id]);
  const { data, error, loading, refresh } = useLoad(load);
  const [addEvidenceVisible, setAddEvidenceVisible] = useState(false);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Sem dados')} retry={refresh} />;
  const { candidate, evidence, checklist, assessments } = data;
  const price = officialEvidence(evidence, 'CURRENT_PRICE');
  const reviews = officialEvidence(evidence, 'REVIEW_SUMMARY');
  const seller = officialEvidence(evidence, 'SELLER_REPUTATION');
  const reviewData = (reviews?.valueJson ?? {}) as Record<string, unknown>;
  const sellerData = (seller?.valueJson ?? {}) as Record<string, unknown>;
  const sellerReputation = (sellerData.sellerReputation ?? sellerData) as Record<string, unknown>;
  const latestOfficialUpdate = [price, reviews, seller].filter((item): item is Evidence => Boolean(item)).sort((left, right) => right.observedAt.localeCompare(left.observedAt))[0];
  return <>
    <header className="page-head"><div><span>CURADORIA</span><h1>{candidate.workingTitle || candidate.externalId || 'Candidato sem título'}</h1><p>{label(candidate.provider)} · {label(candidate.entityType)} · atualizado {date(candidate.updatedAt)}</p></div></header>
    <Section title="Evidence Status"><div className="connection-grid"><div><small>Status</small><Badge tone={statusTone(candidate.evidenceStatus)}>{label(candidate.evidenceStatus)}</Badge></div><div><small>Nível</small><b>{label(candidate.evidenceLevel)}</b></div><div><small>Fluxo</small><b>{label(candidate.status)}</b></div></div><div className="diagnostic-controls"><button onClick={async () => { await api.updateCandidate(id, { status: 'INVESTIGATING' }); refresh(); }}>Investigando</button><button onClick={async () => { await api.updateCandidate(id, { status: 'READY_FOR_REVIEW' }); refresh(); }}>Pronto para revisão</button><button onClick={async () => { await api.archiveCandidate(id); refresh(); }}>Arquivar</button>{candidate.status === 'ARCHIVED' && <button onClick={async () => { await api.reopenCandidate(id); refresh(); }}>Reabrir</button>}</div></Section>
    <Section title="Evidências oficiais"><div className="connection-grid"><div><small>Preço observado</small><b>{formatPrice(price)}</b></div><div><small>Avaliação média</small><b>{unavailable(reviewData.ratingAverage)}</b></div><div><small>Quantidade de avaliações</small><b>{unavailable(reviewData.totalReviews)}</b></div><div><small>Reputação do vendedor</small><b>{unavailable(sellerReputation.level_id ?? sellerReputation.power_seller_status)}</b></div><div><small>Última atualização</small><b>{latestOfficialUpdate ? date(latestOfficialUpdate.observedAt) : 'Não disponível'}</b></div></div></Section>
    <Section title="Checklist"><div className="compact-list">{checklist.items.map(item => <div key={item.key}><b>{item.label}</b><Badge tone={statusTone(item.status)}>{item.status === 'STALE' ? 'Desatualizado' : label(item.status)}</Badge></div>)}</div></Section>
    <AssessmentPanel items={assessments} assess={async () => { await api.assess(id); refresh(); }} />
    <Section title="Evidências"><button className="primary-button" onClick={() => setAddEvidenceVisible(visible => !visible)}>Adicionar evidência</button>{addEvidenceVisible && <form className="diagnostic-controls" onSubmit={async event => { event.preventDefault(); const fields = new FormData(event.currentTarget); await api.addEvidence(id, { evidenceType: fields.get('type'), valueText: fields.get('value') || null, valueCents: ['CURRENT_PRICE', 'PRICE_REFERENCE'].includes(String(fields.get('type'))) ? Math.round(Number(fields.get('value')) * 100) : null, sourceKind: fields.get('source'), confidence: fields.get('confidence'), verificationStatus: fields.get('verification'), validUntil: fields.get('validUntil') || null, metadata: { severity: fields.get('severity'), editorialFlag: fields.get('editorialFlag') || null } }); setAddEvidenceVisible(false); refresh(); }}><select name="type">{['CURRENT_PRICE', 'PRICE_REFERENCE', 'REVIEW_SUMMARY', 'POSITIVE_PATTERN', 'LIMITATION', 'SELLER_REPUTATION', 'TECHNICAL_SPEC', 'USE_CASE', 'DIFFERENTIAL', 'ALTERNATIVE', 'COMMUNITY_SIGNAL', 'OWN_TEST', 'OTHER'].map(type => <option key={type}>{type}</option>)}</select><input name="value" placeholder="Valor ou resumo" /><select name="source"><option>MANUAL_OPERATOR</option><option>PUBLIC_WEB</option><option>COMMUNITY</option><option>OWN_TEST</option></select><select name="confidence"><option>MEDIUM</option><option>HIGH</option><option>VERY_HIGH</option><option>LOW</option></select><select name="verification"><option>UNVERIFIED</option><option>VERIFIED</option><option>DISPUTED</option></select><select name="severity"><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option></select><select name="editorialFlag"><option value="">Sem flag crítica</option><option>SAFETY_RISK</option><option>COUNTERFEIT_RISK</option><option>SEVERE_RECURRING_DEFECT</option><option>MISLEADING_CLAIM</option><option>SELLER_HIGH_RISK</option><option>CRITICAL_INCOMPATIBILITY</option><option>CLEARLY_SUPERIOR_ALTERNATIVE</option><option>EXTREME_OVERPRICE</option><option>UNRESOLVED_CRITICAL_CONTRADICTION</option></select><input name="validUntil" type="datetime-local" /><button>Salvar</button></form>} {evidence.length ? <div className="table-wrap"><table><thead><tr><th>Tipo</th><th>Valor</th><th>Fonte</th><th>Confiança</th><th>Observado</th><th>Estado</th></tr></thead><tbody>{evidence.map(item => <tr key={item.id}><td>{label(item.evidenceType)}</td><td>{item.valueCents !== null && item.valueCents !== undefined ? formatPrice(item) : item.valueText || '—'}</td><td>{label(item.sourceKind)}</td><td>{label(item.confidence)}</td><td>{date(item.observedAt)}</td><td>{item.isStale ? 'Desatualizado' : label(item.verificationStatus)}</td></tr>)}</tbody></table></div> : <Empty>Nenhuma evidência registrada.</Empty>}</Section>
  </>;
}

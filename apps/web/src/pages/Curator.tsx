import { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { Badge, Empty, ErrorState, Loading, Section } from '../components/ui';
import { AssessmentPanel } from '../components/AssessmentPanel';
import { useLoad } from '../hooks';
import { date, label, statusTone } from '../lib/presentation';
import type { CommercialBinding, Evidence, Opportunity } from '../types';

function officialEvidence(evidence: Evidence[], type: string) {
  // Historical evidence remains available for audit, but never represents the
  // current commercial offer in the operator-facing summary.
  return evidence.filter(item => item.evidenceType === type && item.validUntil === null).sort((left, right) => right.observedAt.localeCompare(left.observedAt))[0];
}
function unavailable(value: unknown) { return value === null || value === undefined || value === '' ? 'Não disponível' : String(value); }
function formatPrice(evidence?: Evidence) {
  if (!evidence || evidence.valueCents === null || evidence.valueCents === undefined) return 'Não disponível';
  const metadata = (evidence.valueJson ?? {}) as Record<string, unknown>;
  const currency = typeof metadata.currency === 'string' ? metadata.currency : 'BRL';
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency }).format(evidence.valueCents / 100);
}

function commercialErrorMessage(code: string) {
  if (code === 'CATALOG_PRODUCT_WITHOUT_OFFER') return 'Esta URL identifica um produto de catálogo, mas não uma oferta específica. Use uma URL de item ou uma URL que contenha wid.';
  if (code === 'CATALOG_PRODUCT_MISMATCH_CONFIRMATION_REQUIRED') return 'A oferta selecionada pertence a outro produto de catálogo. Confirme o vínculo para continuar.';
  return code;
}

function CommercialBindingSection({ candidate, binding, busy, message, error, errorCode, offerVisible, affiliateVisible, setOfferVisible, setAffiliateVisible, action }: {
  candidate: { externalId: string | null; sourceRadarRunId: string | null };
  binding: CommercialBinding;
  busy: boolean;
  message: string;
  error: string;
  errorCode: string;
  offerVisible: boolean;
  affiliateVisible: boolean;
  setOfferVisible: (value: boolean) => void;
  setAffiliateVisible: (value: boolean) => void;
  action: (operation: () => Promise<unknown>, successMessage?: string) => Promise<void>;
}) {
  const { id = '' } = useParams();
  // Older API fixtures and cached development responses can predate F2.6.
  // Keep the empty state usable while the server returns the canonical shape.
  const affiliate = binding.affiliate ?? { status: 'NOT_SET', urlPresent: false };
  const linked = Boolean(binding.sourceItemId);
  const bindingIsInvalid = binding.validationStatus === 'INVALID' || binding.validationReasonCode === 'NOT_FOUND';
  const observed = binding.observed ?? {};
  const [offerSource, setOfferSource] = useState(binding.sourceItemId ?? '');
  const mismatchConfirmed = binding.catalogMatchStatus === 'MISMATCH' || errorCode === 'CATALOG_PRODUCT_MISMATCH_CONFIRMATION_REQUIRED';
  return <Section title="Oferta comercial">
    <div className="connection-grid"><div><small>Produto de catálogo</small><b>{binding.catalogProductId ?? candidate.externalId ?? 'Não disponível'}</b></div><div><small>Oferta vinculada</small><b>{binding.sourceItemId ?? 'Nenhuma oferta vinculada'}</b></div><div><small>Status</small><b>{label(binding.validationStatus ?? 'NOT_SET')}</b></div>{linked && <><div><small>Preço observado</small><b>{typeof observed.price === 'number' ? new Intl.NumberFormat('pt-BR', { style: 'currency', currency: observed.currencyId ?? 'BRL' }).format(observed.price) : 'Não disponível'}</b></div><div><small>Vendedor</small><b>{unavailable(observed.sellerId)}</b></div><div><small>Link de afiliado</small><b>{affiliate.urlPresent ? 'Adicionado' : 'Não informado'}</b></div></>}</div>
    {binding.catalogMatchStatus === 'MISMATCH' && <p className="error-state">A oferta selecionada pertence a outro produto de catálogo.</p>}
    {message && <p>{message}</p>}{error && !offerVisible && <p className="error-state">{error}</p>}
    <div className="diagnostic-controls">
      <button type="button" disabled={busy} onClick={() => setOfferVisible(!offerVisible)}>{linked ? 'Alterar oferta' : 'Vincular oferta'}</button>
      {linked && <button type="button" disabled={busy} onClick={() => action(() => api.removeCommercialBinding(id), 'Vínculo comercial removido.')}>Remover vínculo</button>}
      <button type="button" disabled={busy} onClick={() => setAffiliateVisible(!affiliateVisible)}>{affiliate.urlPresent ? 'Alterar link afiliado' : 'Adicionar link de afiliado'}</button>
      <button type="button" disabled={busy || !binding.sourceItemId || bindingIsInvalid} onClick={() => action(() => api.enrichCandidate(id), 'Atualização concluída.')}>{busy ? 'Atualizando…' : 'Atualizar evidências'}</button>
      {typeof observed.permalink === 'string' && <a href={observed.permalink} target="_blank" rel="noreferrer">Abrir oferta</a>}
    </div>
    {offerVisible && <form className="diagnostic-controls" onSubmit={event => { event.preventDefault(); const fields = new FormData(event.currentTarget); action(() => api.bindCommercialOffer(id, { source: offerSource, confirmMismatch: mismatchConfirmed && fields.get('confirmMismatch') === 'on' })); }}><input name="source" required placeholder="Cole a URL ou informe o itemId (MLB123...)" value={offerSource} onChange={event => setOfferSource(event.target.value)} />{error && <p className="error-state" role="alert">{error}</p>}{mismatchConfirmed && Boolean(offerSource.trim()) && <label><input name="confirmMismatch" type="checkbox" /> Confirmo vínculo mesmo se for outro produto de catálogo</label>}<button className="primary-button" disabled={busy}>Salvar oferta</button></form>}
    {affiliateVisible && <form className="diagnostic-controls" onSubmit={event => { event.preventDefault(); const fields = new FormData(event.currentTarget); action(() => api.setCommercialAffiliateUrl(id, { affiliateUrl: String(fields.get('affiliateUrl') ?? ''), confirmReplace: fields.get('confirmReplace') === 'on' })); }}><input name="affiliateUrl" required type="url" placeholder="https://..." defaultValue={affiliate.url ?? ''} /><label><input name="confirmReplace" type="checkbox" /> Confirmo substituir o link atual</label><button className="primary-button" disabled={busy}>Salvar link afiliado</button></form>}
  </Section>;
}

export function CuratorPage() {
  const navigate = useNavigate();
  const load = useCallback(async () => ({ candidates: await api.candidates(), opportunities: await api.opportunities().catch(() => [] as Opportunity[]) }), []);
  const { data, error, loading, refresh } = useLoad(load);
  const [formVisible, setFormVisible] = useState(false);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Sem dados')} retry={refresh} />;
  const countStatus = (status: string) => data.candidates.filter(candidate => candidate.status === status).length;
  const ranked = [...data.candidates].sort((left, right) => (right.triageScore ?? -1) - (left.triageScore ?? -1) || left.id.localeCompare(right.id));
  return <>
    <header className="page-head"><div><span>INVESTIGAÇÃO EDITORIAL</span><h1>Curadoria</h1><p>Candidatos em investigação antes de qualquer recomendação.</p></div><button className="primary-button" onClick={() => setFormVisible(visible => !visible)}>+ Novo candidato</button></header>
    {formVisible && <Section title="Novo candidato"><form className="diagnostic-controls" onSubmit={async event => { event.preventDefault(); const fields = new FormData(event.currentTarget); const candidate = await api.createCandidate({ provider: fields.get('provider'), entityType: fields.get('entityType'), workingTitle: fields.get('title') || null, sourceUrl: fields.get('url') || null, notes: fields.get('notes') || null }); navigate(`/curator/${candidate.id}`); }}><select name="provider"><option value="OTHER">Outro</option><option value="MERCADO_LIVRE">Mercado Livre</option></select><select name="entityType"><option value="MANUAL">Manual</option><option value="ITEM">Item</option><option value="PRODUCT">Produto</option><option value="QUERY">Termo</option></select><input name="title" placeholder="Título de trabalho (opcional)" /><input name="url" placeholder="URL pública (opcional)" /><input name="notes" placeholder="Notas" /><button className="primary-button">Criar</button></form></Section>}
    <div className="metric-grid"><div><b>{countStatus('NEW')}</b><span>Novos</span></div><div><b>{countStatus('INVESTIGATING')}</b><span>Investigando</span></div><div><b>{data.candidates.filter(candidate => candidate.evidenceStatus === 'INSUFFICIENT_EVIDENCE').length}</b><span>Evidência insuficiente</span></div><div><b>{countStatus('READY_FOR_REVIEW')}</b><span>Prontos para revisão</span></div></div>
    <Section title="Oportunidades para revisar">{data.opportunities.length?<div className="compact-list">{data.opportunities.map(item=><Link key={item.candidateId} to={`/curator/${item.candidateId}`}><span><b>{item.title||item.catalogProductId||'Candidato'}</b><small>{item.catalogProductId} · {label(item.triageStatus)} · Triagem {item.triageScore??'—'} · Relevância {item.relevanceScore??'Não disponível'} · {item.sourceCount>1?`Encontrado em ${item.sourceCount} execuções`:'Encontrado em uma execução'} · {item.commercialBindingPresent?'Oferta vinculada':'Sem oferta vinculada'}</small></span><Badge tone={statusTone(item.evidenceStatus)}>{label(item.evidenceStatus)}</Badge><strong>Abrir na Curadoria</strong></Link>)}</div>:<Empty>Nenhuma oportunidade prioritária aguardando revisão.</Empty>}</Section><Section title="Candidatos">{ranked.length ? <div className="compact-list">{ranked.map(candidate => { const reasons = candidate.triageReasons ?? []; return <Link key={candidate.id} to={`/curator/${candidate.id}`}><span><b>{candidate.workingTitle || candidate.externalId || 'Candidato sem título'}</b><small>{label(candidate.sourceType)} · {label(candidate.entityType)} · {candidate.categoryExternalId || 'Sem categoria'}{candidate.triageScore !== null && candidate.triageScore !== undefined ? ` · Triagem ${candidate.triageScore}/100 · ${label(candidate.triageStatus ?? '')}` : ''}{reasons.length ? ` · ${reasons.slice(0, 2).map(label).join(', ')}` : ''}</small></span><Badge tone={statusTone(candidate.evidenceStatus)}>{label(candidate.evidenceStatus)}</Badge><strong>{label(candidate.status)}</strong></Link>; })}</div> : <Empty>Nenhum candidato em curadoria.</Empty>}</Section>
  </>;
}

export function CandidatePage() {
  const { id = '' } = useParams();
  const load = useCallback(async () => { const [candidate, evidence, checklist, assessments, binding] = await Promise.all([api.candidate(id), api.evidence(id), api.checklist(id), api.assessments(id), api.commercialBinding(id)]); return { candidate, evidence, checklist, assessments, binding }; }, [id]);
  const { data, error, loading, refresh } = useLoad(load);
  const [addEvidenceVisible, setAddEvidenceVisible] = useState(false);
  const [offerVisible, setOfferVisible] = useState(false);
  const [affiliateVisible, setAffiliateVisible] = useState(false);
  const [commercialMessage, setCommercialMessage] = useState('');
  const [commercialError, setCommercialError] = useState('');
  const [commercialErrorCode, setCommercialErrorCode] = useState('');
  const [commercialBusy, setCommercialBusy] = useState(false);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Sem dados')} retry={refresh} />;
  const { candidate, evidence, checklist, assessments, binding } = data;
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
    <CommercialBindingSection candidate={candidate} binding={binding} busy={commercialBusy} message={commercialMessage} error={commercialError} errorCode={commercialErrorCode} offerVisible={offerVisible} affiliateVisible={affiliateVisible} setOfferVisible={setOfferVisible} setAffiliateVisible={setAffiliateVisible} action={async (action, successMessage) => { setCommercialBusy(true); setCommercialError(''); setCommercialErrorCode(''); setCommercialMessage(''); try { const result = await action() as { sourceStatuses?: Record<string, { status?: string }> } | undefined; const partial = Object.values(result?.sourceStatuses ?? {}).some(status => status.status === 'FORBIDDEN'); setCommercialMessage(partial ? 'Atualização concluída. Alguns dados comerciais não estão disponíveis.' : successMessage ?? 'Oferta comercial atualizada.'); setOfferVisible(false); setAffiliateVisible(false); await refresh(); } catch (actionError) { const code = actionError instanceof Error ? actionError.message : ''; setCommercialErrorCode(code); setCommercialError(commercialErrorMessage(code || 'Não foi possível atualizar a oferta comercial.')); } finally { setCommercialBusy(false); } }} />
    <Section title="Evidências oficiais"><div className="connection-grid"><div><small>Preço observado</small><b>{formatPrice(price)}</b></div><div><small>Avaliação média</small><b>{unavailable(reviewData.ratingAverage)}</b></div><div><small>Quantidade de avaliações</small><b>{unavailable(reviewData.totalReviews)}</b></div><div><small>Reputação do vendedor</small><b>{unavailable(sellerReputation.level_id ?? sellerReputation.power_seller_status)}</b></div><div><small>Última atualização</small><b>{latestOfficialUpdate ? date(latestOfficialUpdate.observedAt) : 'Não disponível'}</b></div></div></Section>
    <Section title="Checklist"><div className="compact-list">{checklist.items.map(item => <div key={item.key}><b>{item.label}</b><Badge tone={statusTone(item.status)}>{item.status === 'STALE' ? 'Desatualizado' : label(item.status)}</Badge></div>)}</div></Section>
    <AssessmentPanel items={assessments} assess={async () => { await api.assess(id); refresh(); }} />
    <Section title="Evidências"><button className="primary-button" onClick={() => setAddEvidenceVisible(visible => !visible)}>Adicionar evidência</button>{addEvidenceVisible && <form className="diagnostic-controls" onSubmit={async event => { event.preventDefault(); const fields = new FormData(event.currentTarget); await api.addEvidence(id, { evidenceType: fields.get('type'), valueText: fields.get('value') || null, valueCents: ['CURRENT_PRICE', 'PRICE_REFERENCE'].includes(String(fields.get('type'))) ? Math.round(Number(fields.get('value')) * 100) : null, sourceKind: fields.get('source'), confidence: fields.get('confidence'), verificationStatus: fields.get('verification'), validUntil: fields.get('validUntil') || null, metadata: { severity: fields.get('severity'), editorialFlag: fields.get('editorialFlag') || null } }); setAddEvidenceVisible(false); refresh(); }}><select name="type">{['CURRENT_PRICE', 'PRICE_REFERENCE', 'REVIEW_SUMMARY', 'POSITIVE_PATTERN', 'LIMITATION', 'SELLER_REPUTATION', 'TECHNICAL_SPEC', 'USE_CASE', 'DIFFERENTIAL', 'ALTERNATIVE', 'COMMUNITY_SIGNAL', 'OWN_TEST', 'OTHER'].map(type => <option key={type}>{type}</option>)}</select><input name="value" placeholder="Valor ou resumo" /><select name="source"><option>MANUAL_OPERATOR</option><option>PUBLIC_WEB</option><option>COMMUNITY</option><option>OWN_TEST</option></select><select name="confidence"><option>MEDIUM</option><option>HIGH</option><option>VERY_HIGH</option><option>LOW</option></select><select name="verification"><option>UNVERIFIED</option><option>VERIFIED</option><option>DISPUTED</option></select><select name="severity"><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option></select><select name="editorialFlag"><option value="">Sem flag crítica</option><option>SAFETY_RISK</option><option>COUNTERFEIT_RISK</option><option>SEVERE_RECURRING_DEFECT</option><option>MISLEADING_CLAIM</option><option>SELLER_HIGH_RISK</option><option>CRITICAL_INCOMPATIBILITY</option><option>CLEARLY_SUPERIOR_ALTERNATIVE</option><option>EXTREME_OVERPRICE</option><option>UNRESOLVED_CRITICAL_CONTRADICTION</option></select><input name="validUntil" type="datetime-local" /><button>Salvar</button></form>} {evidence.length ? <div className="table-wrap"><table><thead><tr><th>Tipo</th><th>Valor</th><th>Fonte</th><th>Confiança</th><th>Observado</th><th>Estado</th></tr></thead><tbody>{evidence.map(item => <tr key={item.id}><td>{label(item.evidenceType)}</td><td>{item.valueCents !== null && item.valueCents !== undefined ? formatPrice(item) : item.valueText || '—'}</td><td>{label(item.sourceKind)}</td><td>{label(item.confidence)}</td><td>{date(item.observedAt)}</td><td>{item.isStale ? 'Desatualizado' : label(item.verificationStatus)}</td></tr>)}</tbody></table></div> : <Empty>Nenhuma evidência registrada.</Empty>}</Section>
  </>;
}

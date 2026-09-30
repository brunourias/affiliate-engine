import { useCallback, useState } from 'react';
import './OpportunityReview.css';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { Badge, Empty, ErrorState, Loading, Section } from '../components/ui';
import { AssessmentPanel } from '../components/AssessmentPanel';
import { OpportunityReviewActions } from '../components/OpportunityReviewActions';
import { CommercialAnalysisActions } from '../components/CommercialAnalysisActions';
import { CampaignHandoffGate } from '../components/CampaignHandoffGate';
import { commercialBlocker } from '../lib/commercialAnalysis';
import { useLoad } from '../hooks';
import { campaignHandoffLabel, date, label, statusTone } from '../lib/presentation';
import type { CommercialBinding, Evidence, OpportunityReviewStatus } from '../types';

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

function LegacyCuratorPage() {
  const navigate = useNavigate();
  const [reviewStatus,setReviewStatus]=useState<OpportunityReviewStatus>('PENDING');
  const load = useCallback(async () => { const [candidates,opportunities,summary,commercialSummary]=await Promise.all([api.candidates(),api.opportunities(20,reviewStatus),api.opportunityReviewSummary(),reviewStatus==='COMMERCIAL_REVIEW'?api.commercialAnalysisSummary():Promise.resolve(null)]); return {candidates,opportunities,summary,commercialSummary}; }, [reviewStatus]);
  const { data, error, loading, refresh } = useLoad(load);
  const [formVisible, setFormVisible] = useState(false);
  const [batchConfirm, setBatchConfirm] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchMessage, setBatchMessage] = useState('');
  const [batchError, setBatchError] = useState('');
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Sem dados')} retry={refresh} />;
  const countStatus = (status: string) => data.candidates.filter(candidate => candidate.status === status).length;
  const ranked = [...data.candidates].sort((left, right) => (right.triageScore ?? -1) - (left.triageScore ?? -1) || left.id.localeCompare(right.id));
  const runBatch = async () => {
    if (batchBusy) return;
    setBatchBusy(true); setBatchError(''); setBatchMessage('');
    try {
      const result = await api.runCommercialAnalysisBatch();
      setBatchMessage(`Análise concluída: ${result.assessmentAvailable} análises disponíveis, ${result.waitingForOffer} aguardando oferta, ${result.evidencePartial} com evidências parciais, ${result.failed} falhas.`);
      setBatchConfirm(false);
      await refresh();
    } catch (batchRunError) {
      setBatchError(batchRunError instanceof Error ? batchRunError.message : 'Não foi possível concluir as análises comerciais.');
    } finally { setBatchBusy(false); }
  };
  return <>
    <header className="page-head"><div><span>INVESTIGAÇÃO EDITORIAL</span><h1>Curadoria</h1><p>Candidatos em investigação antes de qualquer recomendação.</p></div><button className="primary-button" onClick={() => setFormVisible(visible => !visible)}>+ Novo candidato</button></header>
    {formVisible && <Section title="Novo candidato"><form className="diagnostic-controls" onSubmit={async event => { event.preventDefault(); const fields = new FormData(event.currentTarget); const candidate = await api.createCandidate({ provider: fields.get('provider'), entityType: fields.get('entityType'), workingTitle: fields.get('title') || null, sourceUrl: fields.get('url') || null, notes: fields.get('notes') || null }); navigate(`/curator/${candidate.id}`); }}><select name="provider"><option value="OTHER">Outro</option><option value="MERCADO_LIVRE">Mercado Livre</option></select><select name="entityType"><option value="MANUAL">Manual</option><option value="ITEM">Item</option><option value="PRODUCT">Produto</option><option value="QUERY">Termo</option></select><input name="title" placeholder="Título de trabalho (opcional)" /><input name="url" placeholder="URL pública (opcional)" /><input name="notes" placeholder="Notas" /><button className="primary-button">Criar</button></form></Section>}
    <div className="metric-grid"><div><b>{countStatus('NEW')}</b><span>Novos</span></div><div><b>{countStatus('INVESTIGATING')}</b><span>Investigando</span></div><div><b>{data.candidates.filter(candidate => candidate.evidenceStatus === 'INSUFFICIENT_EVIDENCE').length}</b><span>Evidência insuficiente</span></div><div><b>{countStatus('READY_FOR_REVIEW')}</b><span>Prontos para revisão</span></div></div>
    <Section title="Oportunidades"><div className="metric-grid opportunity-summary"><div><b>{data.summary.pending}</b><span>Pendentes</span></div><div><b>{data.summary.investigate}</b><span>Investigando</span></div><div><b>{data.summary.commercialReview}</b><span>Análise comercial</span></div><div><b>{data.summary.dismissed}</b><span>Descartadas</span></div></div><div className="diagnostic-controls opportunity-tabs">{([['PENDING','Pendentes',data.summary.pending],['INVESTIGATE','Investigando',data.summary.investigate],['COMMERCIAL_REVIEW','Análise comercial',data.summary.commercialReview],['DISMISSED','Descartadas',data.summary.dismissed]] as const).map(([status,text,count])=><button type="button" key={status} className={reviewStatus===status?'primary-button':'ghost-button'} onClick={()=>{setReviewStatus(status);setBatchConfirm(false);setBatchError('');setBatchMessage('');}}>{text} {count}</button>)}</div>{reviewStatus==='COMMERCIAL_REVIEW'&&data.commercialSummary&&<><div className="metric-grid opportunity-summary"><div><b>{data.commercialSummary.notStarted}</b><span>Não iniciadas</span></div><div><b>{data.commercialSummary.waitingForOffer}</b><span>Aguardando oferta</span></div><div><b>{data.commercialSummary.evidencePartial}</b><span>Evidências parciais</span></div><div><b>{data.commercialSummary.assessmentAvailable}</b><span>Análises disponíveis</span></div><div><b>{data.commercialSummary.failed}</b><span>Falhas</span></div></div><div className="diagnostic-controls"><button type="button" className="primary-button" disabled={batchBusy} onClick={()=>setBatchConfirm(true)}>Executar análises comerciais</button>{batchMessage&&<p className="timestamp" role="status">{batchMessage}</p>}{batchError&&<p className="inline-error" role="alert">{batchError}</p>}{batchConfirm&&<div className="opportunity-confirm" role="dialog" aria-label="Confirmar análises comerciais"><p>O sistema consultará as fontes oficiais disponíveis para as oportunidades encaminhadas à análise comercial. Nenhuma campanha ou publicação será criada.</p><button type="button" className="ghost-button" disabled={batchBusy} onClick={()=>setBatchConfirm(false)}>Cancelar</button><button type="button" className="primary-button" disabled={batchBusy} onClick={runBatch}>{batchBusy?'Analisando…':'Confirmar análise'}</button></div>}</div></>}{data.opportunities.length?<div className="compact-list opportunity-list">{data.opportunities.map(item=>{const commercialStatus=item.commercialAnalysisStatus??'NOT_STARTED';return <div key={item.candidateId}><span><b>{item.title||item.catalogProductId||'Candidato'}</b><small>{item.catalogProductId} · {label(item.triageStatus)} · Triagem {item.triageScore??'—'} · Relevância {item.relevanceScore??'Não disponível'} · {item.commercialBindingPresent?'Oferta vinculada':'Sem oferta vinculada'} · {item.sourceCount>1?`Encontrado em ${item.sourceCount} execuções`:'Encontrado em uma execução'}</small>{item.opportunityReviewedAt&&<small>Decidido em {date(item.opportunityReviewedAt)}</small>}{item.opportunityReviewReason&&<small>Motivo: {item.opportunityReviewReason}</small>}{reviewStatus==='COMMERCIAL_REVIEW'&&<><small>Estado da análise: {commercialStatus==='FAILED'?'Falha na análise':label(commercialStatus)}</small><small>Última execução: {item.commercialAnalysisLastRunAt?date(item.commercialAnalysisLastRunAt):'Ainda não executada'}</small>{commercialStatus==='NOT_STARTED'&&<small>Análise comercial ainda não executada.</small>}{item.commercialAnalysisBlocker&&<small>{commercialBlocker(item.commercialAnalysisBlocker)}</small>}{commercialStatus==='WAITING_FOR_OFFER'&&<small>Abra o candidato, vincule uma oferta na seção Oferta comercial e execute a análise novamente.</small>}<CommercialAnalysisActions candidateId={item.candidateId} status={commercialStatus} onDone={async()=>refresh()}/></>}{reviewStatus!=='COMMERCIAL_REVIEW'&&<OpportunityReviewActions candidateId={item.candidateId} status={item.opportunityReviewStatus} onUpdated={refresh}/>}</span><Badge tone={statusTone(item.evidenceStatus)}>{label(item.evidenceStatus)}</Badge><Link to={`/curator/${item.candidateId}`}>Abrir candidato</Link></div>})}</div>:<Empty>{reviewStatus==='PENDING'?'Nenhuma oportunidade aguardando decisão. Execute a busca de oportunidades no Radar para procurar novos candidatos.':reviewStatus==='INVESTIGATE'?'Nenhuma oportunidade está em investigação.':reviewStatus==='COMMERCIAL_REVIEW'?'Nenhuma oportunidade foi encaminhada para análise comercial.':'Nenhuma oportunidade foi descartada.'}</Empty>}</Section><Section title="Candidatos">{ranked.length ? <div className="compact-list">{ranked.map(candidate => { const reasons = candidate.triageReasons ?? []; return <Link key={candidate.id} to={`/curator/${candidate.id}`}><span><b>{candidate.workingTitle || candidate.externalId || 'Candidato sem título'}</b><small>{label(candidate.sourceType)} · {label(candidate.entityType)} · {candidate.categoryExternalId || 'Sem categoria'}{candidate.triageScore !== null && candidate.triageScore !== undefined ? ` · Triagem ${candidate.triageScore}/100 · ${label(candidate.triageStatus ?? '')}` : ''}{reasons.length ? ` · ${reasons.slice(0, 2).map(label).join(', ')}` : ''}</small></span><Badge tone={statusTone(candidate.evidenceStatus)}>{label(candidate.evidenceStatus)}</Badge><strong>{label(candidate.status)}</strong></Link>; })}</div> : <Empty>Nenhum candidato em curadoria.</Empty>}</Section>
  </>;
}

// Kept temporarily while CandidatePage continues to share this module; the
// active CuratorPage below is the compact operator workflow.
void LegacyCuratorPage;

export function CuratorPage() {
  const navigate = useNavigate();
  const [mainView, setMainView] = useState<'OPPORTUNITIES' | 'CANDIDATES'>('OPPORTUNITIES');
  const [reviewStatus, setReviewStatus] = useState<OpportunityReviewStatus>('PENDING');
  const [formVisible, setFormVisible] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [batchConfirm, setBatchConfirm] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchMessage, setBatchMessage] = useState('');
  const [batchError, setBatchError] = useState('');
  const load = useCallback(async () => {
    const [candidates, opportunities, summary, commercialSummary, handoffSummary] = await Promise.all([
      api.candidates(), api.opportunities(20, reviewStatus), api.opportunityReviewSummary(),
      reviewStatus === 'COMMERCIAL_REVIEW' ? api.commercialAnalysisSummary() : Promise.resolve(null),
      reviewStatus === 'COMMERCIAL_REVIEW' ? api.campaignHandoffSummary() : Promise.resolve(null),
    ]);
    return { candidates, opportunities, summary, commercialSummary, handoffSummary };
  }, [reviewStatus]);
  const { data, error, loading, refresh } = useLoad(load);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Sem dados')} retry={refresh} />;

  const ranked = [...data.candidates].sort((left, right) => (right.triageScore ?? -1) - (left.triageScore ?? -1) || left.id.localeCompare(right.id));
  const runBatch = async () => {
    if (batchBusy) return;
    setBatchBusy(true); setBatchError(''); setBatchMessage('');
    try {
      const result = await api.runCommercialAnalysisBatch();
      setBatchMessage(`Análise concluída: ${result.assessmentAvailable} análises disponíveis, ${result.waitingForOffer} aguardando oferta, ${result.evidencePartial} com evidências parciais, ${result.failed} falhas.`);
      setBatchConfirm(false); await refresh();
    } catch (batchRunError) {
      setBatchError(batchRunError instanceof Error ? batchRunError.message : 'Não foi possível concluir as análises comerciais.');
    } finally { setBatchBusy(false); }
  };
  const selectReview = (status: OpportunityReviewStatus) => {
    setReviewStatus(status); setBatchConfirm(false); setBatchError(''); setBatchMessage(''); setExpanded(null);
  };

  return <>
    <header className="page-head curator-head"><div><span>INVESTIGAÇÃO EDITORIAL</span><h1>Curadoria</h1><p>Priorize a próxima decisão.</p></div><button type="button" className="primary-button" onClick={() => setFormVisible(value => !value)}>+ Novo candidato</button></header>
    {formVisible && <Section title="Novo candidato"><form className="diagnostic-controls" onSubmit={async event => { event.preventDefault(); const fields = new FormData(event.currentTarget); const candidate = await api.createCandidate({ provider: fields.get('provider'), entityType: fields.get('entityType'), workingTitle: fields.get('title') || null, sourceUrl: fields.get('url') || null, notes: fields.get('notes') || null }); navigate(`/curator/${candidate.id}`); }}><select name="provider"><option value="OTHER">Outro</option><option value="MERCADO_LIVRE">Mercado Livre</option></select><select name="entityType"><option value="MANUAL">Manual</option><option value="ITEM">Item</option><option value="PRODUCT">Produto</option><option value="QUERY">Termo</option></select><input name="title" placeholder="Título de trabalho (opcional)" /><input name="url" placeholder="URL pública (opcional)" /><input name="notes" placeholder="Notas" /><button className="primary-button">Criar</button></form></Section>}
    <nav className="curator-main-tabs" aria-label="Área da Curadoria"><button type="button" className={mainView === 'OPPORTUNITIES' ? 'primary-button' : 'ghost-button'} onClick={() => setMainView('OPPORTUNITIES')}>Oportunidades</button><button type="button" className={mainView === 'CANDIDATES' ? 'primary-button' : 'ghost-button'} onClick={() => setMainView('CANDIDATES')}>Todos os candidatos</button></nav>
    {mainView === 'CANDIDATES' ? <Section title="Todos os candidatos"><div className="curator-candidate-list compact-list">{ranked.length ? ranked.map(candidate => <Link key={candidate.id} to={`/curator/${candidate.id}`}><span><b>{candidate.workingTitle || candidate.externalId || 'Candidato sem título'}</b><small>{candidate.categoryExternalId || 'Sem categoria'} · Triagem {candidate.triageScore ?? '—'}{candidate.triageStatus ? ` · ${label(candidate.triageStatus)}` : ''}</small></span><Badge tone={statusTone(candidate.evidenceStatus)}>{label(candidate.status)}</Badge></Link>) : <Empty>Nenhum candidato em curadoria.</Empty>}</div></Section> : <Section title="Oportunidades">
      <div className="curator-workflow-tabs">{([['PENDING', 'Pendentes', data.summary.pending], ['INVESTIGATE', 'Investigando', data.summary.investigate], ['COMMERCIAL_REVIEW', 'Análise comercial', data.summary.commercialReview], ['DISMISSED', 'Descartadas', data.summary.dismissed]] as const).map(([status, text, count]) => <button type="button" key={status} className={reviewStatus === status ? 'primary-button' : 'ghost-button'} onClick={() => selectReview(status)}>{text} <b>{count}</b></button>)}</div>
      {reviewStatus === 'COMMERCIAL_REVIEW' && data.commercialSummary && <div className="commercial-toolbar"><div><div className="commercial-summary" aria-label="Resumo da análise comercial"><span>Não iniciadas <b>{data.commercialSummary.notStarted}</b></span><span>Aguardando oferta <b>{data.commercialSummary.waitingForOffer}</b></span><span>Parciais <b>{data.commercialSummary.evidencePartial}</b></span><span>Disponíveis <b>{data.commercialSummary.assessmentAvailable}</b></span><span>Falhas <b>{data.commercialSummary.failed}</b></span></div>{data.commercialSummary.assessmentAvailable>0&&data.handoffSummary&&<div className="commercial-summary handoff-summary" aria-label="Resumo do encaminhamento para campanha"><span>Aguardando decisão <b>{data.handoffSummary.notDecided}</b></span><span>Encaminhadas <b>{data.handoffSummary.approved}</b></span><span>Não encaminhadas <b>{data.handoffSummary.rejected}</b></span><span>Revisão necessária <b>{data.handoffSummary.stale}</b></span></div>}</div><div className="commercial-batch"><button type="button" className="primary-button" disabled={batchBusy} onClick={() => setBatchConfirm(true)}>Executar análises comerciais</button>{batchConfirm && <div className="opportunity-confirm" role="dialog" aria-label="Confirmar análises comerciais"><p>O sistema consultará as fontes oficiais disponíveis para as oportunidades encaminhadas à análise comercial. Nenhuma campanha ou publicação será criada.</p><button type="button" className="ghost-button" disabled={batchBusy} onClick={() => setBatchConfirm(false)}>Cancelar</button><button type="button" className="primary-button" disabled={batchBusy} onClick={runBatch}>{batchBusy ? 'Analisando…' : 'Confirmar análise'}</button></div>}</div>{batchMessage && <p className="timestamp" role="status">{batchMessage}</p>}{batchError && <p className="inline-error" role="alert">{batchError}</p>}</div>}
      {data.opportunities.length ? <div className="opportunity-cards">{data.opportunities.map(item => {
        const commercialStatus = item.commercialAnalysisStatus ?? 'NOT_STARTED';
        const isCommercial = reviewStatus === 'COMMERCIAL_REVIEW';
        const isExpanded = expanded === item.candidateId;
        const commercialLabel = commercialStatus === 'FAILED' ? 'Falha na análise' : label(commercialStatus);
        const actionMessage = commercialStatus === 'NOT_STARTED' ? 'Análise comercial ainda não foi executada.' : commercialStatus === 'ASSESSMENT_AVAILABLE' ? 'Análise comercial concluída.' : commercialStatus === 'FAILED' ? 'Não foi possível concluir a análise comercial.' : commercialBlocker(item.commercialAnalysisBlocker);
        return <article className="opportunity-card" key={item.candidateId}><div className="opportunity-card-head"><div><h3>{item.title || item.catalogProductId || 'Candidato'}</h3><p>{item.catalogProductId ?? 'Sem produto de catálogo'} · Triagem {item.triageScore ?? '—'}{item.relevanceScore !== null ? ` · Relevância ${item.relevanceScore}` : ''} · {item.commercialBindingPresent ? 'Oferta vinculada' : 'Sem oferta'}</p></div><Badge tone={isCommercial && commercialStatus === 'FAILED' ? 'danger' : isCommercial && commercialStatus === 'ASSESSMENT_AVAILABLE' ? 'success' : 'neutral'}>{isCommercial ? commercialLabel : label(item.evidenceStatus)}</Badge></div>{isCommercial && <p className="opportunity-card-message">{actionMessage || 'Análise comercial atualizada.'}</p>}{isCommercial&&commercialStatus==='ASSESSMENT_AVAILABLE'&&<CampaignHandoffGate candidateId={item.candidateId} status={item.campaignHandoffStatus??'NOT_DECIDED'} compact onDone={refresh}/>}<div className="opportunity-card-actions">{isCommercial ? <CommercialAnalysisActions candidateId={item.candidateId} status={commercialStatus} onDone={async () => refresh()} /> : <OpportunityReviewActions candidateId={item.candidateId} status={item.opportunityReviewStatus} onUpdated={refresh} />}{isCommercial && (commercialStatus === 'EVIDENCE_PARTIAL' || commercialStatus === 'FAILED') && <Link className="ghost-button" to={`/curator/${item.candidateId}`}>Abrir candidato</Link>}<button type="button" className="ghost-button" onClick={() => setExpanded(isExpanded ? null : item.candidateId)}>{isExpanded ? 'Ocultar detalhes' : 'Detalhes'}</button></div>{isExpanded && <div className="opportunity-card-details"><small>Última decisão: {item.opportunityReviewedAt ? date(item.opportunityReviewedAt) : 'Ainda não revisada'}</small>{item.opportunityReviewReason && <small>Motivo: {item.opportunityReviewReason}</small>}{isCommercial && <><small>Última execução comercial: {item.commercialAnalysisLastRunAt ? date(item.commercialAnalysisLastRunAt) : 'Ainda não executada'}</small><small>Gate para campanha: {campaignHandoffLabel(item.campaignHandoffStatus)}</small><small>Evidências gerais: {label(item.evidenceStatus)} · Nível: {label(item.evidenceLevel)}</small></>}<small>Encontrado em {item.sourceCount} {item.sourceCount === 1 ? 'execução' : 'execuções'}.</small><Link to={`/curator/${item.candidateId}`}>Abrir candidato</Link></div>}</article>;
      })}</div> : <Empty>{reviewStatus === 'COMMERCIAL_REVIEW' ? 'Nenhuma oportunidade foi encaminhada para análise comercial.' : 'Nenhuma oportunidade nesta etapa.'}</Empty>}
    </Section>}
  </>;
}

export function CandidatePage() {
  const { id = '' } = useParams();
  const load = useCallback(async () => { const [candidate, evidence, checklist, assessments, binding] = await Promise.all([api.candidate(id), api.evidence(id), api.checklist(id), api.assessments(id), api.commercialBinding(id)]); const handoff=candidate.commercialAnalysisStatus==='ASSESSMENT_AVAILABLE'?await api.campaignHandoff(id):null; return { candidate, evidence, checklist, assessments, binding, handoff }; }, [id]);
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
  const { candidate, evidence, checklist, assessments, binding, handoff } = data;
  const commercialStatus = candidate.commercialAnalysisStatus ?? 'NOT_STARTED';
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
    <Section title="Revisão da oportunidade"><div className="connection-grid"><div><small>Status</small><b>{label(candidate.opportunityReviewStatus)}</b></div><div><small>Decidido em</small><b>{candidate.opportunityReviewedAt?date(candidate.opportunityReviewedAt):'Ainda não revisada'}</b></div>{candidate.opportunityReviewReason&&<div><small>Motivo</small><b>{candidate.opportunityReviewReason}</b></div>}</div><OpportunityReviewActions candidateId={candidate.id} status={candidate.opportunityReviewStatus} onUpdated={refresh}/></Section>
    <Section title="Análise comercial"><div className="connection-grid"><div><small>Status</small><b>{commercialStatus==='FAILED'?'Falha na análise':label(commercialStatus)}</b></div><div><small>Última execução</small><b>{candidate.commercialAnalysisLastRunAt?date(candidate.commercialAnalysisLastRunAt):'Ainda não executada'}</b></div>{candidate.commercialAnalysisBlocker&&<div><small>Pendência</small><b>{commercialBlocker(candidate.commercialAnalysisBlocker)}</b></div>}</div>{candidate.opportunityReviewStatus==='COMMERCIAL_REVIEW'?<><CommercialAnalysisActions candidateId={candidate.id} status={commercialStatus} onDone={async()=>refresh()}/>{commercialStatus==='WAITING_FOR_OFFER'&&<p>Vincule uma oferta na seção Oferta comercial e execute a análise novamente.</p>}{commercialStatus==='ASSESSMENT_AVAILABLE'&&<p>Análise disponível. Veja o resultado na seção Avaliação.</p>}</>:<p>A análise comercial só pode ser executada após encaminhar esta oportunidade para Análise comercial.</p>}</Section>
    {commercialStatus==='ASSESSMENT_AVAILABLE'&&<Section title="Encaminhamento para campanha"><div className="connection-grid"><div><small>Status</small><Badge tone={statusTone(handoff?.status??candidate.campaignHandoffStatus)}>{campaignHandoffLabel(handoff?.status??candidate.campaignHandoffStatus)}</Badge></div><div><small>Análise usada na decisão</small><b>v{handoff?.assessmentVersion??'—'}</b></div><div><small>Análise atual</small><b>v{handoff?.currentAssessmentVersion??'—'}</b></div>{handoff?.reviewedAt&&<div><small>Data da decisão</small><b>{date(handoff.reviewedAt)}</b></div>}{handoff?.reason&&<div><small>Motivo</small><b>{handoff.reason}</b></div>}</div><CampaignHandoffGate candidateId={candidate.id} status={handoff?.status??candidate.campaignHandoffStatus??'NOT_DECIDED'} onDone={refresh} showStatus={false}/></Section>}
    <CommercialBindingSection candidate={candidate} binding={binding} busy={commercialBusy} message={commercialMessage} error={commercialError} errorCode={commercialErrorCode} offerVisible={offerVisible} affiliateVisible={affiliateVisible} setOfferVisible={setOfferVisible} setAffiliateVisible={setAffiliateVisible} action={async (action, successMessage) => { setCommercialBusy(true); setCommercialError(''); setCommercialErrorCode(''); setCommercialMessage(''); try { const result = await action() as { sourceStatuses?: Record<string, { status?: string }> } | undefined; const partial = Object.values(result?.sourceStatuses ?? {}).some(status => status.status === 'FORBIDDEN'); setCommercialMessage(partial ? 'Atualização concluída. Alguns dados comerciais não estão disponíveis.' : successMessage ?? 'Oferta comercial atualizada.'); setOfferVisible(false); setAffiliateVisible(false); await refresh(); } catch (actionError) { const code = actionError instanceof Error ? actionError.message : ''; setCommercialErrorCode(code); setCommercialError(commercialErrorMessage(code || 'Não foi possível atualizar a oferta comercial.')); } finally { setCommercialBusy(false); } }} />
    <Section title="Evidências oficiais"><div className="connection-grid"><div><small>Preço observado</small><b>{formatPrice(price)}</b></div><div><small>Avaliação média</small><b>{unavailable(reviewData.ratingAverage)}</b></div><div><small>Quantidade de avaliações</small><b>{unavailable(reviewData.totalReviews)}</b></div><div><small>Reputação do vendedor</small><b>{unavailable(sellerReputation.level_id ?? sellerReputation.power_seller_status)}</b></div><div><small>Última atualização</small><b>{latestOfficialUpdate ? date(latestOfficialUpdate.observedAt) : 'Não disponível'}</b></div></div></Section>
    <Section title="Checklist"><div className="compact-list">{checklist.items.map(item => <div key={item.key}><b>{item.label}</b><Badge tone={statusTone(item.status)}>{item.status === 'STALE' ? 'Desatualizado' : label(item.status)}</Badge></div>)}</div></Section>
    <AssessmentPanel items={assessments} assess={async () => { await api.assess(id); refresh(); }} />
    <Section title="Evidências"><button className="primary-button" onClick={() => setAddEvidenceVisible(visible => !visible)}>Adicionar evidência</button>{addEvidenceVisible && <form className="diagnostic-controls" onSubmit={async event => { event.preventDefault(); const fields = new FormData(event.currentTarget); await api.addEvidence(id, { evidenceType: fields.get('type'), valueText: fields.get('value') || null, valueCents: ['CURRENT_PRICE', 'PRICE_REFERENCE'].includes(String(fields.get('type'))) ? Math.round(Number(fields.get('value')) * 100) : null, sourceKind: fields.get('source'), confidence: fields.get('confidence'), verificationStatus: fields.get('verification'), validUntil: fields.get('validUntil') || null, metadata: { severity: fields.get('severity'), editorialFlag: fields.get('editorialFlag') || null } }); setAddEvidenceVisible(false); refresh(); }}><select name="type">{['CURRENT_PRICE', 'PRICE_REFERENCE', 'REVIEW_SUMMARY', 'POSITIVE_PATTERN', 'LIMITATION', 'SELLER_REPUTATION', 'TECHNICAL_SPEC', 'USE_CASE', 'DIFFERENTIAL', 'ALTERNATIVE', 'COMMUNITY_SIGNAL', 'OWN_TEST', 'OTHER'].map(type => <option key={type}>{type}</option>)}</select><input name="value" placeholder="Valor ou resumo" /><select name="source"><option>MANUAL_OPERATOR</option><option>PUBLIC_WEB</option><option>COMMUNITY</option><option>OWN_TEST</option></select><select name="confidence"><option>MEDIUM</option><option>HIGH</option><option>VERY_HIGH</option><option>LOW</option></select><select name="verification"><option>UNVERIFIED</option><option>VERIFIED</option><option>DISPUTED</option></select><select name="severity"><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option></select><select name="editorialFlag"><option value="">Sem flag crítica</option><option>SAFETY_RISK</option><option>COUNTERFEIT_RISK</option><option>SEVERE_RECURRING_DEFECT</option><option>MISLEADING_CLAIM</option><option>SELLER_HIGH_RISK</option><option>CRITICAL_INCOMPATIBILITY</option><option>CLEARLY_SUPERIOR_ALTERNATIVE</option><option>EXTREME_OVERPRICE</option><option>UNRESOLVED_CRITICAL_CONTRADICTION</option></select><input name="validUntil" type="datetime-local" /><button>Salvar</button></form>} {evidence.length ? <div className="table-wrap"><table><thead><tr><th>Tipo</th><th>Valor</th><th>Fonte</th><th>Confiança</th><th>Observado</th><th>Estado</th></tr></thead><tbody>{evidence.map(item => <tr key={item.id}><td>{label(item.evidenceType)}</td><td>{item.valueCents !== null && item.valueCents !== undefined ? formatPrice(item) : item.valueText || '—'}</td><td>{label(item.sourceKind)}</td><td>{label(item.confidence)}</td><td>{date(item.observedAt)}</td><td>{item.isStale ? 'Desatualizado' : label(item.verificationStatus)}</td></tr>)}</tbody></table></div> : <Empty>Nenhuma evidência registrada.</Empty>}</Section>
  </>;
}

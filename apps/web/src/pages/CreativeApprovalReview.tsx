import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiRequestError } from '../api/client';
import { campaignsApi } from '../api/campaigns';
import { creativesApi } from '../api/creatives';
import { Badge, ErrorState, Loading, Section } from '../components/ui';
import { creativeStatusLabel, date, label, statusTone } from '../lib/presentation';
import type { Approval, Campaign, Creative, CreativeReadiness } from '../types';

type CreativeApprovalBundle = { creative: Creative; readiness: CreativeReadiness; campaign: Campaign };
type Confirmation = 'approve' | 'reject' | null;

export function CreativeApprovalReview({ initialApproval }: { initialApproval: Approval }) {
  const [approval, setApproval] = useState(initialApproval);
  const [bundle, setBundle] = useState<CreativeApprovalBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [reason, setReason] = useState('');
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');

  const loadBundle = useCallback(async (item: Approval) => {
    if (!item.entityId) throw new Error('A aprovação não possui um criativo associado.');
    const creative = await creativesApi.get(item.entityId);
    const [readiness, campaign] = await Promise.all([
      creativesApi.readiness(creative.id), campaignsApi.get(creative.campaignId),
    ]);
    return { creative, readiness, campaign };
  }, []);

  const refresh = useCallback(async () => {
    const current = await api.approval(initialApproval.id);
    setApproval(current);
    setBundle(await loadBundle(current));
  }, [initialApproval.id, loadBundle]);

  useEffect(() => {
    let active = true;
    setLoading(true); setLoadError(null);
    void (async () => {
      try {
        const current = await api.approval(initialApproval.id);
        const nextBundle = await loadBundle(current);
        if (active) { setApproval(current); setBundle(nextBundle); }
      } catch (caught) {
        if (active) setLoadError(caught instanceof Error ? caught : new Error('Não foi possível carregar o contexto atual do criativo.'));
      } finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, [initialApproval.id, loadBundle]);

  const decide = async () => {
    if (!confirmation || busyRef.current || approval.status !== 'PENDING') return;
    busyRef.current = true; setBusy(true); setActionError(''); setNotice('');
    const decision = confirmation;
    try {
      const updated = await api.decide(approval.id, decision, reason.trim());
      setApproval(updated); setConfirmation(null);
      setNotice(decision === 'approve' ? 'Criativo aprovado.' : 'Criativo rejeitado.');
      try { await refresh(); }
      catch { setNotice('Decisão registrada. Não foi possível atualizar todos os dados; atualize a página para conferir o estado atual.'); }
    } catch (caught) {
      const code = caught instanceof ApiRequestError ? caught.code : null;
      if (code === 'CREATIVE_APPROVAL_INVALIDATED') {
        setActionError('O criativo mudou desde o envio e precisa ser revisado antes da aprovação.');
        setConfirmation(null);
        try { await refresh(); } catch { /* Preserve the primary decision error. */ }
      } else if (code === 'APPROVAL_DECISION_CONFLICT') {
        setActionError('Esta solicitação já foi decidida em outra sessão.');
        setNotice('O estado atual da aprovação foi recarregado.'); setConfirmation(null);
        try { await refresh(); } catch { /* Preserve the primary decision error. */ }
      } else if (code === 'CREATIVE_APPROVAL_STATE_INCONSISTENT') {
        setActionError('O estado desta aprovação está inconsistente. Atualize os dados e procure uma nova solicitação pendente antes de decidir.');
        setConfirmation(null);
        try { await refresh(); } catch { /* Preserve the primary decision error. */ }
      } else {
        setActionError(caught instanceof Error ? caught.message : 'Não foi possível registrar a decisão.');
      }
    } finally { busyRef.current = false; setBusy(false); }
  };

  if (loading) return <Loading />;
  if (loadError) return <ErrorState error={loadError} retry={() => { setLoading(true); void refresh().then(() => setLoadError(null)).catch(caught => setLoadError(caught instanceof Error ? caught : new Error('Não foi possível atualizar.'))).finally(() => setLoading(false)); }} />;
  if (!bundle) return <ErrorState error={new Error('Contexto do criativo indisponível.')} retry={() => undefined} />;

  const { creative, readiness, campaign } = bundle;
  const pending = approval.status === 'PENDING';
  const blockers = readiness.blockers ?? [];
  const warnings = readiness.warnings ?? [];
  const hasBlockers = blockers.length > 0;
  const blockerNeedsCampaign = (blocker: { code: string; field?: string | null }) =>
    blocker.field === 'campaignId' || blocker.field === 'sourceCampaignApprovalId' || blocker.field === 'sourceAssessmentId' ||
    blocker.code.startsWith('CAMPAIGN_') || blocker.code.startsWith('SOURCE_');

  return <div className="approval-workspace creative-approval-workspace">
    <Link className="approval-back" to="/aprovacoes">← Voltar para aprovações</Link>
    <header className="approval-hero">
      <div className="approval-hero-copy"><span className="approval-eyebrow">APROVAÇÃO DE CRIATIVO</span><h1>{approval.title}</h1>
        <div className="approval-hero-meta"><span>Solicitação: <Badge tone={statusTone(approval.status)}>{label(approval.status)}</Badge></span><span>Enviada em {date(approval.createdAt)}</span>{approval.decidedAt && <span>Decidida em {date(approval.decidedAt)}</span>}<span>Criativo atual: <Badge tone={statusTone(creative.status)}>{creativeStatusLabel(creative.status)}</Badge></span></div>
      </div>
    </header>
    {notice && <p className="approval-live success" role="status" aria-live="polite">{notice}</p>}
    {actionError && <p className="approval-error" role="alert">{actionError}</p>}

    <Section title="Contexto atual do criativo">
      <div className="approval-facts creative-approval-facts">
        <Fact label="Nome" value={creative.name} /><Fact label="Campanha" value={<Link to={`/campanhas/${campaign.id}`}>{campaign.name}</Link>} /><Fact label="Status da campanha" value={label(campaign.status)} />
        <Fact label="Status atual" value={creativeStatusLabel(creative.status)} /><Fact label="Formato" value={label(creative.contentType)} />
        <Fact label="Canal" value={label(creative.targetChannel)} /><Fact label="Origem" value={creative.creationSource ? label(creative.creationSource) : 'Não informada'} />
        <Fact label="Experimento" value={creative.experimentId ? 'Associado' : 'Não associado'} /><Fact label="Título" value={creative.title || 'Não informado'} />
        <Fact label="Premissa" value={creative.contentPremise || 'Não informada'} /><Fact label="Abertura" value={creative.hook || 'Não informada'} />
        <Fact label="Roteiro" value={creative.bodyScript || 'Não informado'} /><Fact label="Chamada para ação" value={creative.cta || 'Não informada'} />
        <Fact label="Duração estimada" value={creative.estimatedDurationSeconds == null ? 'Não informada' : `${creative.estimatedDurationSeconds} s`} />
        <Fact label="Cenas" value={readiness.sceneCount} /><Fact label="Aviso de afiliação" value={creative.disclosureText || 'Não informado'} />
        <Fact label="Conformidade atual" value={<Badge tone={statusTone(readiness.compliance.status)}>{label(readiness.compliance.status)}</Badge>} />
      </div>
      {creative.requiredWarnings.length > 0 && <div className="creative-approval-list"><h3>Advertências</h3><ul>{creative.requiredWarnings.map((item, index) => <li key={`${item.code}-${index}`}>{item.message || label(item.code)}</li>)}</ul></div>}
      {creative.forbiddenClaims.length > 0 && <div className="creative-approval-list"><h3>Alegações proibidas</h3><ul>{creative.forbiddenClaims.map(code => <li key={code}>{label(code)}</li>)}</ul></div>}
      <Link className="ghost-button small approval-context-link" to={`/criativos/${creative.id}`}>Abrir criativo</Link>
    </Section>

    <Section title="Prontidão atual">
      {blockers.length === 0 ? <p className="approval-ready">Nenhum bloqueio atual para decisão.</p> : <div className="approval-blocker-panel"><p>A aprovação está bloqueada enquanto os itens abaixo não forem resolvidos.</p><ul>{blockers.map((blocker, index) => { const campaignBlocker = blockerNeedsCampaign(blocker); return <li key={`${blocker.code}-${index}`}><span>{blocker.message || label(blocker.code)}</span> <Link to={campaignBlocker ? `/campanhas/${campaign.id}` : `/criativos/${creative.id}`}>{campaignBlocker ? 'Abrir campanha' : 'Abrir criativo'}</Link></li>; })}</ul></div>}
      {warnings.length > 0 && <div className="creative-approval-list"><h3>Avisos — não bloqueiam a decisão</h3><ul>{warnings.map((warning, index) => <li key={`${warning.code}-${index}`}>{warning.message || label(warning.code)}</li>)}</ul></div>}
      {readiness.compliance.reasons.length > 0 && <div className="creative-approval-list"><h3>Conformidade</h3><ul>{readiness.compliance.reasons.map((item, index) => <li key={`${item.code}-${index}`}>{item.message}</li>)}</ul></div>}
    </Section>

    {pending ? <Section title="Decisão humana">
      <div className="approval-decision-composer">
        {hasBlockers && <p className="approval-lock-note">A aprovação está bloqueada até que o criativo atenda aos requisitos atuais. A solicitação pode ser rejeitada.</p>}
        <label htmlFor="creative-approval-reason">Motivo da decisão <span>(opcional)</span></label>
        <textarea id="creative-approval-reason" maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} aria-describedby="creative-approval-reason-count" />
        <small id="creative-approval-reason-count" className="approval-character-count">{reason.length} / 1000</small>
        {confirmation ? <div className="approval-confirmation" role="group" aria-label="Confirmar decisão"><p>{confirmation === 'approve' ? 'Confirmar aprovação deste criativo?' : 'Confirmar rejeição deste criativo?'}</p><div><button type="button" className="ghost-button" disabled={busy} onClick={() => setConfirmation(null)}>Cancelar</button><button type="button" className={confirmation === 'approve' ? 'primary-button' : 'danger-button'} disabled={busy} onClick={() => void decide()}>{busy ? confirmation === 'approve' ? 'Aprovando…' : 'Rejeitando…' : confirmation === 'approve' ? 'Confirmar aprovação' : 'Confirmar rejeição'}</button></div></div> : <div className="approval-decision-actions"><button type="button" className="primary-button" disabled={busy || hasBlockers} onClick={() => setConfirmation('approve')}>Aprovar</button><button type="button" className="danger-button" disabled={busy} onClick={() => setConfirmation('reject')}>Rejeitar</button></div>}
      </div>
    </Section> : <Section title="Decisão desta solicitação">
      <div className="approval-decision-summary"><div><small>Status da solicitação</small><Badge tone={statusTone(approval.status)}>{label(approval.status)}</Badge></div><div><small>Decidida em</small><b>{date(approval.decidedAt)}</b></div><div className="approval-decision-reason"><small>Motivo</small><p>{approval.decisionReason || 'Sem motivo informado.'}</p></div></div>
      {approval.status === 'APPROVED' && <p className="approval-outcome">Criativo aprovado. Nenhuma renderização de mídia ou publicação foi executada.</p>}
      {approval.status === 'REJECTED' && <p className="approval-outcome">Criativo rejeitado. O conteúdo pode ser corrigido e enviado novamente para revisão.</p>}
      <Link className="primary-button small" to={`/criativos/${creative.id}`}>Abrir criativo</Link>
    </Section>}

    <details className="approval-audit-details"><summary>Resumo enviado para aprovação</summary><pre>{approval.description}</pre></details>
    <details className="approval-audit-details"><summary>Detalhes técnicos</summary><dl><div><dt>ID da aprovação</dt><dd>{approval.id}</dd></div><div><dt>Tipo da entidade</dt><dd>{approval.entityType ? label(approval.entityType) : '—'}</dd></div><div><dt>ID da entidade</dt><dd>{approval.entityId || '—'}</dd></div><div><dt>Solicitada em</dt><dd>{date(approval.createdAt)}</dd></div><div><dt>Atualizada em</dt><dd>{date(approval.updatedAt)}</dd></div></dl></details>
  </div>;
}

function Fact({ label: title, value }: { label: string; value: import('react').ReactNode }) { return <div className="approval-fact"><small>{title}</small><b>{value}</b></div>; }

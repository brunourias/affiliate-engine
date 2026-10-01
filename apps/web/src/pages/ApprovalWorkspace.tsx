import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiRequestError } from '../api/client';
import { campaignsApi } from '../api/campaigns';
import { CreativeApprovalReview } from './CreativeApprovalReview';
import { Badge, ErrorState, Loading, Section } from '../components/ui';
import { date, label, statusTone } from '../lib/presentation';
import type { Approval, Campaign, CampaignAngle, CampaignChannel, CampaignExperiment, CampaignReadiness } from '../types';
import './ApprovalWorkspace.css';

type CampaignBundle = { campaign: Campaign; readiness: CampaignReadiness; channels: CampaignChannel[]; angles: CampaignAngle[]; experiments: CampaignExperiment[] };
type Confirmation = 'approve' | 'reject' | null;
const campaignRelated = (item: Approval) => item.type === 'CAMPAIGN' && item.entityType === 'CAMPAIGN' && Boolean(item.entityId);
const isRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const sensitivePayloadKey = /token|secret|password|authorization|auth.?code/i;
function redactPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redactPayload);
  if (!isRecord(value)) return value;
  return Object.fromEntries(Object.entries(value).map(([key, nested]) => [key, sensitivePayloadKey.test(key) ? '[ocultado]' : redactPayload(nested)]));
}

export function ApprovalWorkspace() {
  const { id = '' } = useParams();
  const [approval, setApproval] = useState<Approval | null>(null);
  const [bundle, setBundle] = useState<CampaignBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [reason, setReason] = useState('');
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');

  const refreshWorkspace = useCallback(async () => {
    const item = await api.approval(id);
    setApproval(item);
    if (!campaignRelated(item)) {
      setBundle(null);
      return;
    }
    const campaignId = item.entityId!;
    const [campaign, readiness, channels, angles, experiments] = await Promise.all([
      campaignsApi.get(campaignId), campaignsApi.readiness(campaignId), campaignsApi.channels(campaignId),
      campaignsApi.angles(campaignId), campaignsApi.experiments(campaignId),
    ]);
    setBundle({ campaign, readiness, channels, angles, experiments });
  }, [id]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError(null);
    void (async () => {
      try {
        const item = await api.approval(id);
        let nextBundle: CampaignBundle | null = null;
        if (campaignRelated(item)) {
          const campaignId = item.entityId!;
          const [campaign, readiness, channels, angles, experiments] = await Promise.all([
            campaignsApi.get(campaignId), campaignsApi.readiness(campaignId), campaignsApi.channels(campaignId),
            campaignsApi.angles(campaignId), campaignsApi.experiments(campaignId),
          ]);
          nextBundle = { campaign, readiness, channels, angles, experiments };
        }
        if (active) { setApproval(item); setBundle(nextBundle); }
      } catch (error) {
        if (active) setLoadError(error instanceof Error ? error : new Error('Não foi possível carregar a aprovação.'));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [id]);

  const decide = async () => {
    if (!approval || !confirmation || busyRef.current) return;
    busyRef.current = true;
    setBusy(true); setActionError(''); setNotice('');
    const decision = confirmation;
    try {
      const updated = await api.decide(approval.id, decision, reason.trim() || '');
      setApproval(updated);
      setConfirmation(null);
      setNotice(decision === 'approve' ? 'Aprovação registrada.' : 'Rejeição registrada.');
      try { await refreshWorkspace(); }
      catch { setNotice('Decisão registrada. Não foi possível atualizar todos os dados; atualize a página para conferir o estado atual.'); }
    } catch (error) {
      const code = error instanceof ApiRequestError ? error.code : null;
      if (code === 'CAMPAIGN_APPROVAL_INVALIDATED') {
        setActionError('A campanha mudou desde o envio e precisa ser revisada antes da aprovação.');
        setConfirmation(null);
        try { await refreshWorkspace(); } catch { /* Preserve the primary decision error. */ }
      } else if (code === 'APPROVAL_DECISION_CONFLICT') {
        setNotice('Esta solicitação já foi decidida em outra sessão. O estado atual foi recarregado.');
        setActionError('Esta solicitação já foi decidida em outra sessão.');
        setConfirmation(null);
        try { await refreshWorkspace(); } catch { /* Preserve the primary decision error. */ }
      } else {
        setActionError(error instanceof Error ? error.message : 'Não foi possível registrar a decisão.');
      }
    } finally {
      busyRef.current = false; setBusy(false);
    }
  };

  if (loading) return <Loading />;
  if (loadError) return <ErrorState error={loadError} retry={() => { setLoading(true); void refreshWorkspace().then(() => setLoadError(null)).catch(error => setLoadError(error instanceof Error ? error : new Error('Não foi possível carregar a aprovação.'))).finally(() => setLoading(false)); }} />;
  if (!approval) return <ErrorState error={new Error('Aprovação não encontrada.')} retry={() => undefined} />;

  if (approval.type === 'CREATIVE' && approval.entityType === 'CREATIVE' && approval.entityId) {
    return <CreativeApprovalReview key={approval.id} initialApproval={approval} />;
  }

  const isCampaign = campaignRelated(approval);
  const pending = approval.status === 'PENDING';
  const blockers = bundle?.readiness.blockers ?? [];
  const hasBlockers = isCampaign && blockers.length > 0;
  const codes = new Set(blockers.map(blocker => blocker.code));
  const needsCurator = codes.has('ASSESSMENT_OUTDATED') || ['INSUFFICIENT_EVIDENCE', 'TRUST_GATE_BLOCKED', 'EDITORIAL_VERDICT_NOT_ELIGIBLE'].some(code => codes.has(code));
  const payload = approval.requestedPayload;
  const financialSpend = isRecord(payload) && payload.requiresFinancialSpend === true;

  return <div className="approval-workspace">
    <Link className="approval-back" to="/aprovacoes">← Voltar para aprovações</Link>
    <header className="approval-hero">
      <div className="approval-hero-copy"><span className="approval-eyebrow">{isCampaign ? 'APROVAÇÃO DE CAMPANHA' : `APROVAÇÃO · ${label(approval.type).toLocaleUpperCase('pt-BR')}`}</span><h1>{approval.title}</h1><div className="approval-hero-meta"><Badge tone={statusTone(approval.status)}>{label(approval.status)}</Badge><span>Enviada em {date(approval.createdAt)}</span>{approval.decidedAt && <span>Decidida em {date(approval.decidedAt)}</span>}</div></div>
    </header>

    {notice && <p className="approval-live success" role="status" aria-live="polite">{notice}</p>}

    {isCampaign && bundle && <>
      <CampaignContext bundle={bundle} />
      {financialSpend && <aside className="approval-financial-warning" role="note"><b>Gasto financeiro previsto</b><p>Esta campanha prevê gasto financeiro, que continua dependendo de autorização separada.</p></aside>}
      {pending && <Section title="Condição atual para aprovação">
        {blockers.length === 0 ? <p className="approval-ready" role="status">Os requisitos atuais continuam válidos.</p> : <div className="approval-blocker-panel"><p>A campanha mudou desde o envio e não pode ser aprovada neste momento.</p>
          {codes.has('ASSESSMENT_OUTDATED') && <p className="approval-special-blocker">A análise comercial mudou após o envio desta campanha.</p>}
          {['INSUFFICIENT_EVIDENCE', 'TRUST_GATE_BLOCKED', 'EDITORIAL_VERDICT_NOT_ELIGIBLE'].some(code => codes.has(code)) && <p className="approval-special-blocker">A condição editorial atual não permite aprovação.</p>}
          <ul>{blockers.map((blocker, index) => <li key={`${blocker.code}-${index}`}>{blocker.message || label(blocker.code)}</li>)}</ul>
          {needsCurator && <Link className="ghost-button small" to={`/curator/${bundle.campaign.candidateId}`}>Abrir oportunidade</Link>}
        </div>}
      </Section>}
    </>}

    {approval.status !== 'PENDING' ? <Section title="Decisão desta solicitação">
      <div className="approval-decision-summary"><div><small>Status</small><Badge tone={statusTone(approval.status)}>{label(approval.status)}</Badge></div><div><small>Decidida em</small><b>{date(approval.decidedAt)}</b></div><div className="approval-decision-reason"><small>Motivo</small><p>{approval.decisionReason || 'Sem motivo informado.'}</p></div></div>
      {approval.status === 'APPROVED' && <p className="approval-outcome">{isCampaign ? 'Campanha aprovada. Nenhum criativo foi criado automaticamente.' : 'Esta solicitação foi aprovada.'}</p>}
      {approval.status === 'REJECTED' && <p className="approval-outcome">{isCampaign ? 'A campanha voltou para revisão e pode ser corrigida e reenviada.' : 'Esta solicitação foi rejeitada.'}</p>}
      {isCampaign && <Link className="primary-button small" to={`/campanhas/${approval.entityId}`}>Abrir campanha</Link>}
    </Section> : <Section title="Decisão">
      <div className="approval-decision-composer">
        {hasBlockers && <p className="approval-lock-note">A aprovação está bloqueada até que a campanha seja revisada.</p>}
        <label htmlFor="approval-reason">Motivo da decisão <span>(opcional)</span></label>
        <textarea id="approval-reason" maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} aria-describedby="approval-reason-count" />
        <small id="approval-reason-count" className="approval-character-count">{reason.length} / 1000</small>
        {actionError && <p className="approval-error" role="alert">{actionError}</p>}
        {confirmation ? <div className="approval-confirmation" role="group" aria-label="Confirmar decisão">
          <p>{confirmation === 'approve' ? `Confirmar aprovação ${isCampaign ? 'desta campanha' : 'desta solicitação'}?` : 'Confirmar rejeição desta solicitação?'}</p>
          <div><button type="button" className="ghost-button" disabled={busy} onClick={() => setConfirmation(null)}>Cancelar</button><button type="button" className={confirmation === 'approve' ? 'primary-button' : 'danger-button'} disabled={busy} onClick={() => void decide()}>{busy ? confirmation === 'approve' ? 'Aprovando…' : 'Rejeitando…' : confirmation === 'approve' ? 'Confirmar aprovação' : 'Confirmar rejeição'}</button></div>
        </div> : <div className="approval-decision-actions">
          <button type="button" className="primary-button" disabled={busy || Boolean(hasBlockers)} onClick={() => setConfirmation('approve')}>Aprovar</button>
          <button type="button" className="danger-button" disabled={busy} onClick={() => setConfirmation('reject')}>Rejeitar</button>
        </div>}
      </div>
    </Section>}

    <details className="approval-audit-details"><summary>Resumo enviado para aprovação</summary><pre>{approval.description}</pre></details>
    <details className="approval-audit-details"><summary>Detalhes técnicos</summary><dl><div><dt>ID da aprovação</dt><dd>{approval.id}</dd></div><div><dt>Tipo da entidade</dt><dd>{approval.entityType || '—'}</dd></div><div><dt>ID da entidade</dt><dd>{approval.entityId || '—'}</dd></div><div><dt>Solicitada em</dt><dd>{date(approval.createdAt)}</dd></div><div><dt>Atualizada em</dt><dd>{date(approval.updatedAt)}</dd></div>{payload && <div><dt>Payload solicitado</dt><dd><pre>{JSON.stringify(redactPayload(payload), null, 2)}</pre></dd></div>}</dl></details>
  </div>;
}

function CampaignContext({ bundle }: { bundle: CampaignBundle }) {
  const { campaign, channels, angles, experiments } = bundle;
  return <>
    <Section title="Campanha atual"><div className="approval-facts">
      <Fact label="Nome" value={campaign.name} /><Fact label="Status atual da campanha" value={<Badge tone={statusTone(campaign.status)}>{label(campaign.status)}</Badge>} /><Fact label="Objetivo" value={label(campaign.objective)} /><Fact label="Prioridade" value={label(campaign.campaignPriority)} />
    </div><Link className="ghost-button small approval-context-link" to={`/campanhas/${campaign.id}`}>Abrir campanha</Link></Section>
    <Section title="Origem editorial"><div className="approval-facts">
      <Fact label="Qualidade das evidências no envio" value={label(campaign.trustGateSnapshot)} /><Fact label="Veredito editorial" value={label(campaign.editorialVerdictSnapshot)} /><Fact label="Pontuação de recomendação" value={campaign.recommendationScoreSnapshot ?? 'Não informado'} /><Fact label="Pontuação de oportunidade" value={campaign.opportunityScoreSnapshot ?? 'Não informado'} /><Fact label="Veredito de preço" value={label(campaign.priceVerdictSnapshot)} />
    </div></Section>
    <Section title="Estratégia"><div className="approval-facts">
      <Fact label="Público" value={campaign.targetAudience || 'Não informado'} /><Fact label="Posicionamento" value={campaign.editorialPositioning || 'Não informado'} /><Fact label="Mensagem principal" value={campaign.primaryMessage || 'Não informado'} /><Fact label="Chamada para ação" value={campaign.ctaStrategy || 'Não informado'} /><Fact label="Disclosure" value={campaign.disclosureText || 'Não informado'} />
    </div></Section>
    <Section title="Execução planejada"><div className="approval-planned-grid"><div><b>Canais habilitados</b><div className="approval-chip-list">{channels.filter(channel => channel.enabled).length ? channels.filter(channel => channel.enabled).map(channel => <Badge key={channel.id}>{label(channel.channel)}</Badge>) : <span>Não há canais habilitados.</span>}</div></div><Fact label="Ângulos" value={angles.filter(angle => angle.status === 'ACTIVE').length} /><Fact label="Experimentos" value={experiments.filter(experiment => experiment.status === 'PLANNED').length} /></div></Section>
  </>;
}

function Fact({ label: title, value }: { label: string; value: import('react').ReactNode }) { return <div className="approval-fact"><small>{title}</small><b>{value}</b></div>; }

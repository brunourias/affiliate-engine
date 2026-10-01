import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { campaignsApi } from "../api/campaigns";
import { creativesApi } from "../api/creatives";
import { ApiRequestError } from "../lib/apiError";
import { creativeHandoffReasonMessage, creativeStatusLabel, label, statusTone } from "../lib/presentation";
import type { Campaign, CampaignAngle, CampaignChannel, CampaignExperiment, CreativeHandoffState } from "../types";
import { Badge } from "./ui";

type Props = { campaign: Campaign; channels: CampaignChannel[]; angles: CampaignAngle[]; experiments: CampaignExperiment[] };
const unapprovedMessages: Record<string, string> = {
  DRAFT: "A campanha ainda precisa ser revisada e aprovada antes de iniciar um criativo.",
  PENDING_APPROVAL: "A criação do criativo ficará disponível após a aprovação humana da campanha.",
  REJECTED: "A campanha precisa ser revisada e aprovada novamente antes de criar um criativo.",
  PAUSED: "Uma campanha pausada não pode iniciar um novo criativo.",
  ARCHIVED: "Uma campanha arquivada não pode iniciar um novo criativo.",
};
const approvalsReasons = new Set(["CAMPAIGN_APPROVAL_REQUIRED", "CAMPAIGN_APPROVAL_STATE_INCONSISTENT"]);
const curatorReasons = new Set(["ASSESSMENT_OUTDATED", "INSUFFICIENT_EVIDENCE", "TRUST_GATE_BLOCKED", "EDITORIAL_VERDICT_NOT_ELIGIBLE"]);
const strategyReasons = new Set(["TARGET_AUDIENCE_REQUIRED", "EDITORIAL_POSITIONING_REQUIRED", "PRIMARY_MESSAGE_REQUIRED", "CTA_REQUIRED", "DISCLOSURE_REQUIRED", "AFFILIATE_LINK_REQUIRED", "AFFILIATE_LINK_NOT_VERIFIED"]);
const anchors: Record<string, string> = {
  CHANNEL_REQUIRED: "campaign-channels", CREATIVE_TARGET_CHANNEL_REQUIRED: "campaign-channels", CREATIVE_TARGET_CHANNEL_NOT_ENABLED: "campaign-channels",
  ANGLE_REQUIRED: "campaign-angles", EXPERIMENT_REQUIRED: "campaign-experiments", EXPERIMENT_ANGLE_NOT_ELIGIBLE: "campaign-angles",
  EXPERIMENT_CHANNEL_NOT_ENABLED: "campaign-experiments",
  AFFILIATE_LINK_REQUIRED: "campaign-destination", AFFILIATE_LINK_NOT_VERIFIED: "campaign-destination",
  TARGET_AUDIENCE_REQUIRED: "campaign-strategy", EDITORIAL_POSITIONING_REQUIRED: "campaign-strategy", PRIMARY_MESSAGE_REQUIRED: "campaign-strategy", CTA_REQUIRED: "campaign-strategy", DISCLOSURE_REQUIRED: "campaign-strategy",
};

export function CampaignCreativeHandoff({ campaign, channels, angles, experiments }: Props) {
  const [originExperimentId, setOriginExperimentId] = useState("");
  const [channelSelection, setChannelSelection] = useState("");
  const [handoff, setHandoff] = useState<CreativeHandoffState | null>(null);
  const [checking, setChecking] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const requestSequence = useRef(0);
  const createLock = useRef(false);
  const enabledChannels = channels.filter((item) => item.enabled);
  const angleTitles = new Map(angles.map((item) => [item.id, item.title]));
  const selectedExperiment = experiments.find((item) => item.id === originExperimentId) ?? null;

  const refreshHandoff = useCallback(async (experimentId: string, targetChannel: string) => {
    const sequence = ++requestSequence.current;
    setHandoff(null);
    setChecking(true);
    setError("");
    try {
      const next = await campaignsApi.creativeHandoff(campaign.id, experimentId || undefined, targetChannel || undefined);
      if (sequence === requestSequence.current) setHandoff(next);
      return sequence === requestSequence.current ? next : null;
    } catch (cause) {
      if (sequence === requestSequence.current) setError(cause instanceof Error ? cause.message : "Não foi possível verificar a próxima etapa.");
      return null;
    } finally {
      if (sequence === requestSequence.current) setChecking(false);
    }
  }, [campaign.id]);

  useEffect(() => {
    void refreshHandoff("", "");
    return () => { requestSequence.current += 1; };
  }, [campaign.id, refreshHandoff]); // Each selection change explicitly requests only the new handoff context.

  const chooseOrigin = (value: string) => {
    setOriginExperimentId(value);
    setChannelSelection("");
    setNotice("");
    void refreshHandoff(value, "");
  };
  const chooseChannel = (value: string) => {
    setChannelSelection(value);
    setNotice("");
    void refreshHandoff(originExperimentId, value);
  };
  const scrollTo = (id: string) => {
    const target = document.getElementById(id);
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
    target?.focus({ preventScroll: true });
  };

  const createCreative = async () => {
    if (createLock.current || creating || checking || handoff?.state !== "READY_TO_CREATE") return;
    createLock.current = true;
    setCreating(true);
    setError("");
    setNotice("");
    const body: Record<string, unknown> = {};
    if (originExperimentId) body.experimentId = originExperimentId;
    if (channelSelection) body.targetChannel = channelSelection;
    try {
      const created = await creativesApi.create(campaign.id, body);
      setNotice("Este criativo já está disponível como rascunho.");
      const refreshed = await refreshHandoff(originExperimentId, channelSelection);
      if (!refreshed) {
        setError("");
        setHandoff({
          state: "CREATIVE_EXISTS", campaignId: campaign.id, campaignStatus: campaign.status,
          approvalId: created.sourceCampaignApprovalId, assessmentId: created.sourceAssessmentId,
          experimentId: created.experimentId, creativeId: created.id, creativeName: created.name,
          creativeStatus: created.status, targetChannel: created.targetChannel, reasonCode: null,
        });
      }
    } catch (cause) {
      const code = cause instanceof ApiRequestError ? cause.code : null;
      if (["CAMPAIGN_CREATIVE_HANDOFF_INVALIDATED", "CREATIVE_HANDOFF_CONFLICT", "MULTIPLE_CREATIVES_FOR_CAMPAIGN", "MULTIPLE_CREATIVES_FOR_EXPERIMENT"].includes(code ?? "")) {
        const refreshed = await refreshHandoff(originExperimentId, channelSelection);
        if (refreshed?.state === "CREATIVE_EXISTS") setNotice("Este criativo já está disponível.");
        else if (refreshed?.state === "MULTIPLE_CREATIVES") setNotice("Há mais de um criativo inicial associado a esta origem.");
        else if (!refreshed) setError("Não foi possível atualizar a situação da criação. Verifique a campanha antes de tentar novamente.");
        else if (refreshed.state === "NOT_ELIGIBLE") setNotice(creativeHandoffReasonMessage(refreshed.reasonCode));
        else setError(creativeHandoffReasonMessage(code));
      } else if (code) {
        setError(creativeHandoffReasonMessage(code));
      } else {
        setError(cause instanceof Error ? cause.message : "Não foi possível criar o rascunho do criativo.");
      }
    } finally {
      createLock.current = false;
      setCreating(false);
    }
  };

  const reason = handoff?.reasonCode ?? null;
  const channelChoiceRequired = reason === "CREATIVE_TARGET_CHANNEL_REQUIRED" || reason === "EXPERIMENT_TARGET_CHANNEL_CONFLICT" || reason === "CREATIVE_TARGET_CHANNEL_NOT_ENABLED";
  const fixedExperimentChannel = selectedExperiment?.targetChannel ?? null;
  const displayedChannel = handoff?.targetChannel ?? fixedExperimentChannel;
  const unapprovedMessage = campaign.status !== "APPROVED" ? unapprovedMessages[campaign.status] : null;

  return <section className="panel campaign-creative-handoff" aria-labelledby="creative-handoff-title">
    <div className="campaign-panel-heading">
      <div><span className="campaign-kicker">PRÓXIMA ETAPA EDITORIAL</span><h2 id="creative-handoff-title">Criação do criativo</h2></div>
      {handoff && <Badge tone={handoff.state === "READY_TO_CREATE" ? "success" : handoff.state === "MULTIPLE_CREATIVES" ? "warning" : statusTone(handoff.state)}>{label(handoff.state)}</Badge>}
    </div>
    {checking && <p className="campaign-handoff-status" role="status">Verificando próxima etapa…</p>}
    {error && <p className="campaign-child-error" role="alert">{error}</p>}
    {!checking && !error && handoff?.state === "NOT_ELIGIBLE" && <div className="campaign-handoff-body">
      <p>{unapprovedMessage ?? creativeHandoffReasonMessage(reason)}</p>
      {reason && approvalsReasons.has(reason) && <Link className="secondary-button" to="/aprovacoes">Ver aprovações</Link>}
      {reason === "ASSESSMENT_OUTDATED" && <Link className="secondary-button" to={`/curator/${campaign.candidateId}`}>Abrir oportunidade</Link>}
      {reason && curatorReasons.has(reason) && reason !== "ASSESSMENT_OUTDATED" && <Link className="secondary-button" to={`/curator/${campaign.candidateId}`}>Abrir oportunidade</Link>}
      {reason && strategyReasons.has(reason) && <button type="button" className="secondary-button" onClick={() => scrollTo("campaign-strategy")}>Revisar campanha</button>}
      {reason && anchors[reason] && !strategyReasons.has(reason) && <button type="button" className="secondary-button" onClick={() => scrollTo(anchors[reason])}>Revisar campanha</button>}
    </div>}
    {!checking && !error && handoff?.state === "READY_TO_CREATE" && <div className="campaign-handoff-body">
      <p className="campaign-handoff-ready">A campanha continua válida e possui autorização humana para iniciar a etapa criativa.</p>
      <dl className="campaign-handoff-context">
        <div><dt>Origem</dt><dd>{selectedExperiment ? `Experimento: ${selectedExperiment.hypothesis}` : "Campanha aprovada"}</dd></div>
        <div><dt>Canal</dt><dd>{displayedChannel ? label(displayedChannel) : "A definir"}</dd></div>
        {selectedExperiment?.angleId && <div><dt>Ângulo</dt><dd>{angleTitles.get(selectedExperiment.angleId) ?? "Ângulo não disponível"}</dd></div>}
        <div><dt>Autorização</dt><dd>Campanha aprovada por decisão humana</dd></div>
      </dl>
      <p className="campaign-handoff-scope">Criar o criativo inicia apenas um rascunho editorial. Não serão geradas cenas, mídia, aprovação ou publicação automaticamente.</p>
      {campaign.requiresFinancialSpend && <p className="campaign-handoff-warning" role="note">Esta campanha prevê gasto financeiro. A criação do criativo não autoriza esse gasto.</p>}
      <details className="campaign-handoff-technical"><summary>Detalhes da autorização</summary><div><span>Approval ID<b>{handoff.approvalId ?? "—"}</b></span><span>Assessment ID<b>{handoff.assessmentId ?? "—"}</b></span>{handoff.experimentId && <span>Experiment ID<b>{handoff.experimentId}</b></span>}</div></details>
      <button type="button" className="primary-button" disabled={creating || checking || handoff.state !== "READY_TO_CREATE"} onClick={() => void createCreative()}>{creating ? "Criando…" : "Criar criativo"}</button>
    </div>}
    {!checking && !error && handoff?.state === "CREATIVE_EXISTS" && <div className="campaign-handoff-body">
      <p className="campaign-handoff-ready">{notice || "O criativo inicial associado a esta origem já foi criado."}</p>
      <dl className="campaign-handoff-context"><div><dt>Criativo</dt><dd>{handoff.creativeName || "Criativo"}</dd></div><div><dt>Status</dt><dd>{handoff.creativeStatus ? creativeStatusLabel(handoff.creativeStatus) : "Não informado"}</dd></div><div><dt>Canal</dt><dd>{handoff.targetChannel ? label(handoff.targetChannel) : "Não informado"}</dd></div></dl>
      {handoff.creativeId && <Link className="primary-button" to={`/criativos/${handoff.creativeId}`}>Abrir criativo</Link>}
    </div>}
    {!checking && !error && handoff?.state === "MULTIPLE_CREATIVES" && <div className="campaign-handoff-body">
      <p className="campaign-handoff-warning">Há mais de um criativo inicial associado a esta origem.</p>
      <p>O sistema não escolherá um automaticamente.</p>
      <Link className="secondary-button" to="/criativos">Abrir lista de criativos</Link>
    </div>}
    {!error && !unapprovedMessage && <div className="campaign-handoff-choice">
      <label htmlFor="creative-handoff-origin">Origem do criativo<select id="creative-handoff-origin" value={originExperimentId} disabled={creating} onChange={(event) => chooseOrigin(event.target.value)}><option value="">Campanha aprovada — usar estratégia base</option>{experiments.map((experiment) => <option key={experiment.id} value={experiment.id} disabled={creating || experiment.status !== "PLANNED"}>{experiment.hypothesis} · {label(experiment.status)}{experiment.targetChannel ? ` · ${label(experiment.targetChannel)}` : ""}</option>)}</select></label>
      {selectedExperiment && <p className="campaign-handoff-experiment-meta">Status: {label(selectedExperiment.status)}{selectedExperiment.targetChannel ? ` · Canal: ${label(selectedExperiment.targetChannel)}` : " · Canal definido pela campanha"}{selectedExperiment.angleId ? ` · Ângulo: ${angleTitles.get(selectedExperiment.angleId) ?? "Ângulo não disponível"}` : ""}</p>}
      {channelChoiceRequired && !fixedExperimentChannel && enabledChannels.length > 0 && <label htmlFor="creative-handoff-channel">Escolha o canal deste criativo<select id="creative-handoff-channel" value={channelSelection} disabled={creating} onChange={(event) => chooseChannel(event.target.value)}><option value="">Selecione um canal</option>{enabledChannels.map((channel) => <option key={channel.id} value={channel.channel}>{label(channel.channel)}</option>)}</select></label>}
    </div>}
  </section>;
}

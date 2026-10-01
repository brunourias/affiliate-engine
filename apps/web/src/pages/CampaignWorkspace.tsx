import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { campaignsApi } from "../api/campaigns";
import { AffiliateDestination } from "../components/AffiliateDestination";
import { Badge, Empty, ErrorState, Loading } from "../components/ui";
import { useLoad } from "../hooks";
import { campaignNextActionLabel, isCampaignEditable, label, statusTone } from "../lib/presentation";
import { formatDateTime } from "../lib/presentation";
import type { Campaign, CampaignAngle, CampaignChannel, CampaignExperiment, CampaignReadiness } from "../types";
import "./CampaignPage.css";

type Workspace = { c: Campaign; channels: CampaignChannel[]; angles: CampaignAngle[]; experiments: CampaignExperiment[]; ready: CampaignReadiness };
type StrategyDraft = { objective: string; audience: string; positioning: string; message: string; cta: string; disclosure: string };
type CommercialDraft = { url: string; verified: boolean };
const strategyFrom = (c: Campaign): StrategyDraft => ({ objective: c.objective, audience: c.targetAudience ?? "", positioning: c.editorialPositioning ?? "", message: c.primaryMessage ?? "", cta: c.ctaStrategy ?? "", disclosure: c.disclosureText ?? "" });
const commercialFrom = (c: Campaign): CommercialDraft => ({ url: c.affiliateUrl ?? "", verified: !!c.affiliateUrlVerifiedAt });
const lockedMessage: Record<string, string> = {
  PENDING_APPROVAL: "O conteúdo permanece bloqueado até a decisão humana.",
  APPROVED: "A Campaign está aprovada para seguir às próximas etapas editoriais.",
  PAUSED: "Esta Campaign está pausada e disponível somente para consulta.",
  ARCHIVED: "Esta Campaign está arquivada e disponível somente para consulta.",
  REJECTED: "A campanha foi rejeitada. Você pode ajustar o conteúdo e enviar novamente quando estiver pronta.",
};
const readinessGroups = [
  { title: "Origem editorial", keys: ["assessment", "sourceAssessmentCurrent", "trustGate", "editorialVerdict"] },
  { title: "Estratégia", keys: ["targetAudience", "editorialPositioning", "primaryMessage", "cta"] },
  { title: "Comercial", keys: ["affiliateLink", "affiliateLinkVerified", "disclosure"] },
  { title: "Execução", keys: ["channel", "angle", "experiment"] },
];
const actionHelp: Record<string, string> = {
  REVIEW_UPDATED_ASSESSMENT: "A análise vinculada mudou. Revise a oportunidade na Curadoria; esta Campaign não será atualizada automaticamente.",
  RESOLVE_EVIDENCE: "A análise de origem ainda não permite avançar. Completar os campos da Campaign não contorna essa decisão.",
  COMPLETE_STRATEGY: "Complete os campos editoriais obrigatórios antes do envio para aprovação.",
  CONFIGURE_AFFILIATE_LINK: "Este objetivo exige um link de afiliado na própria Campaign.",
  VERIFY_AFFILIATE_LINK: "O link configurado precisa ser verificado antes do envio.",
  ADD_CHANNEL: "Adicione ao menos um canal habilitado para esta Campaign.",
  ADD_ANGLE: "Adicione ao menos um ângulo editorial ativo.",
  ADD_EXPERIMENT: "Adicione ao menos um experimento válido.",
  READY_TO_SUBMIT: "Todos os requisitos editoriais foram atendidos. O envio cria uma solicitação pendente para decisão humana.",
  AWAITING_APPROVAL: "A Campaign foi enviada para decisão humana.",
};
const anchorForAction: Record<string, string> = {
  COMPLETE_STRATEGY: "campaign-strategy", CONFIGURE_AFFILIATE_LINK: "campaign-destination", VERIFY_AFFILIATE_LINK: "campaign-destination",
  ADD_CHANNEL: "campaign-channels", ADD_ANGLE: "campaign-angles", ADD_EXPERIMENT: "campaign-experiments",
};

export function CampaignWorkspace() {
  const { id = "" } = useParams();
  const load = useCallback(async (): Promise<Workspace> => {
    const [c, channels, angles, experiments, ready] = await Promise.all([campaignsApi.get(id), campaignsApi.channels(id), campaignsApi.angles(id), campaignsApi.experiments(id), campaignsApi.readiness(id)]);
    return { c, channels, angles, experiments, ready };
  }, [id]);
  const { data, error, loading, refresh, setData } = useLoad(load);
  const [strategy, setStrategy] = useState<StrategyDraft | null>(null);
  const [commercial, setCommercial] = useState<CommercialDraft | null>(null);
  const [initializedFor, setInitializedFor] = useState("");
  const [strategySaving, setStrategySaving] = useState(false);
  const [commercialSaving, setCommercialSaving] = useState(false);
  const [strategyMessage, setStrategyMessage] = useState("");
  const [commercialMessage, setCommercialMessage] = useState("");
  const [submitBusy, setSubmitBusy] = useState(false);
  const submitLock = useRef(false);
  const [submitMessage, setSubmitMessage] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [childBusy, setChildBusy] = useState("");
  const [childError, setChildError] = useState("");
  const [channelDraft, setChannelDraft] = useState("TIKTOK");
  const [angleDraft, setAngleDraft] = useState({ type: "SMART_BUYING", title: "", premise: "" });
  const [experimentDraft, setExperimentDraft] = useState({ angleId: "", hypothesis: "", hook: "", cta: "", channel: "" });

  useEffect(() => {
    if (!data || data.c.id !== id || initializedFor === id) return;
    setStrategy(strategyFrom(data.c));
    setCommercial(commercialFrom(data.c));
    setInitializedFor(id);
  }, [data, id, initializedFor]);

  const refreshWorkspace = async () => {
    const latest = await load();
    setData(latest);
    return latest;
  };
  if (loading && (!data || data.c.id !== id)) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error("Sem dados")} retry={refresh} />;
  if (data.c.id !== id) return <Loading />;
  const { c, channels, angles, experiments, ready } = data;
  const editable = isCampaignEditable(c.status);
  const strategyDraft = strategy ?? strategyFrom(c);
  const commercialDraft = commercial ?? commercialFrom(c);
  const strategyDirty = JSON.stringify(strategyDraft) !== JSON.stringify(strategyFrom(c));
  const commercialDirty = JSON.stringify(commercialDraft) !== JSON.stringify(commercialFrom(c));
  const checks = ready.checks ?? {};
  const blockers = ready.blockers ?? [];
  const warnings = ready.warnings ?? [];
  const checkEntries = Object.entries(checks);
  const passedCount = checkEntries.filter(([, value]) => value).length;
  const nextAction = ready.nextAction ?? "NONE";
  const locked = !editable;
  const candidateAssessmentBlocker = blockers.some((item) => item.code === "ASSESSMENT_OUTDATED");
  const evidenceBlocker = blockers.some((item) => ["INSUFFICIENT_EVIDENCE", "TRUST_GATE_BLOCKED", "EDITORIAL_VERDICT_NOT_ELIGIBLE"].includes(item.code));
  const angleTitles = new Map(angles.map((angle) => [angle.id, angle.title]));
  const existingChannels = new Set(channels.map((channel) => channel.channel));
  const displayedDisclosureText = new Set([c.disclosureText, strategyDraft.disclosure].map((value) => value.trim()).filter(Boolean));
  const distinctRequiredDisclosures = c.requiredDisclosures.filter((item) => !displayedDisclosureText.has(item.trim()));
  const strategySet = (key: keyof StrategyDraft, value: string) => {
    setStrategy((previous) => ({ ...(previous ?? strategyFrom(c)), [key]: value }));
    setStrategyMessage("Alterações não salvas");
  };
  const commercialSet = (key: keyof CommercialDraft, value: string | boolean) => {
    setCommercial((previous) => ({ ...(previous ?? commercialFrom(c)), [key]: value }));
    setCommercialMessage("Alterações não salvas");
  };
  const submitCampaign = async () => {
    if (submitLock.current || ready.state !== "READY_FOR_APPROVAL" || nextAction !== "READY_TO_SUBMIT") return;
    submitLock.current = true;
    setSubmitBusy(true); setSubmitError(""); setSubmitMessage("");
    try {
      await campaignsApi.submit(id);
      setData((previous) => previous ? { ...previous, c: { ...previous.c, status: "PENDING_APPROVAL" }, ready: { ...previous.ready, state: "PENDING_APPROVAL", campaignStatus: "PENDING_APPROVAL", nextAction: "AWAITING_APPROVAL" } } : previous);
      setSubmitMessage("Campaign enviada para aprovação.");
      try { await refreshWorkspace(); }
      catch { setSubmitMessage("Campaign enviada para aprovação. Não foi possível atualizar todos os dados; atualize a página para confirmar o estado."); }
    } catch (cause) {
      setSubmitError(cause instanceof Error ? cause.message : "Não foi possível enviar a Campaign para aprovação.");
    } finally { submitLock.current = false; setSubmitBusy(false); }
  };
  const saveStrategy = async (event: FormEvent) => {
    event.preventDefault();
    if (!editable || !strategyDirty || strategySaving) return;
    setStrategySaving(true); setStrategyMessage("Salvando…");
    try {
      await campaignsApi.patch(id, { objective: strategyDraft.objective, targetAudience: strategyDraft.audience, editorialPositioning: strategyDraft.positioning, primaryMessage: strategyDraft.message, ctaStrategy: strategyDraft.cta, disclosureText: strategyDraft.disclosure });
      const latest = await refreshWorkspace();
      setStrategy(strategyFrom(latest.c)); setStrategyMessage("Estratégia salva. Preparação atualizada.");
    } catch (cause) {
      setStrategyMessage(cause instanceof Error ? cause.message : "Não foi possível salvar a estratégia.");
    } finally { setStrategySaving(false); }
  };
  const saveCommercial = async (event: FormEvent) => {
    event.preventDefault();
    if (!editable || !commercialDirty || commercialSaving) return;
    setCommercialSaving(true); setCommercialMessage("Salvando…");
    try {
      await campaignsApi.patch(id, { affiliateUrl: commercialDraft.url || null, affiliateUrlVerified: commercialDraft.verified });
      const latest = await refreshWorkspace();
      setCommercial(commercialFrom(latest.c)); setCommercialMessage("Destino salvo. Preparação atualizada.");
    } catch (cause) {
      setCommercialMessage(cause instanceof Error ? cause.message : "Não foi possível salvar o destino comercial.");
    } finally { setCommercialSaving(false); }
  };
  const runChildAction = async (key: string, action: () => Promise<unknown>, onSuccess?: () => void) => {
    if (childBusy) return;
    setChildBusy(key); setChildError("");
    try { await action(); await refreshWorkspace(); onSuccess?.(); }
    catch (cause) { setChildError(cause instanceof Error ? cause.message : "Não foi possível atualizar a configuração editorial."); }
    finally { setChildBusy(""); }
  };
  const goToNextAction = () => {
    const targetId = anchorForAction[nextAction];
    if (!targetId) return;
    const target = document.getElementById(targetId);
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
    target?.focus({ preventScroll: true });
  };
  const lockMessage = lockedMessage[c.status];
  const stateTitle = c.status === "PENDING_APPROVAL" ? "Aguardando aprovação" : c.status === "APPROVED" ? "Campanha aprovada" : c.status === "PAUSED" ? "Campanha pausada" : c.status === "ARCHIVED" ? "Campanha arquivada" : c.status === "REJECTED" ? "Revisão da campanha" : ready.state === "READY_FOR_APPROVAL" ? "Campanha pronta para aprovação" : "Campanha em preparação";
  const nextActionTitle = campaignNextActionLabel(nextAction);

  return <main className="campaign-workspace">
    <header className="campaign-hero">
      <Link className="campaign-back" to="/campanhas">← Voltar para campanhas</Link>
      <div className="campaign-hero-main">
        <div className="campaign-hero-copy">
          <span className="campaign-eyebrow">{label("Campaign Workspace").toLocaleUpperCase("pt-BR")}</span>
          <h1>{c.name}</h1>
          <p>{label(c.objective)} <span aria-hidden="true">·</span> Oportunidade: {label(c.editorialVerdictSnapshot)}</p>
        </div>
        <div className="campaign-hero-badges">
          <Badge tone={statusTone(c.status)}>{label(c.status)}</Badge>
          <Badge tone={statusTone(c.campaignPriority)}>{label(c.campaignPriority)}</Badge>
        </div>
      </div>
      <div className="campaign-hero-meta">
        <span><small>Qualidade das evidências</small><b>{label(c.trustGateSnapshot)}</b></span>
        <span><small>{label("Recommendation")}</small><b>{c.recommendationScoreSnapshot ?? "—"}</b></span>
        <span><small>{label("Opportunity")}</small><b>{c.opportunityScoreSnapshot ?? "—"}</b></span>
        <span><small>Preço</small><b>{label(c.priceVerdictSnapshot)}</b></span>
      </div>
      {lockMessage && <p className="campaign-lock-note" role="status">{lockMessage}</p>}
      <details className="campaign-technical"><summary>Detalhes técnicos e origem</summary><div><span>Campaign ID<b>{c.id}</b></span><span>Candidate ID<b>{c.candidateId}</b></span><span>Assessment ID<b>{c.assessmentId}</b></span><span>Criada em<b>{formatDateTime(c.createdAt)}</b></span><span>Atualizada em<b>{formatDateTime(c.updatedAt)}</b></span></div></details>
    </header>

    <div className="campaign-focus-grid">
      <section className={`campaign-next-action ${nextAction === "READY_TO_SUBMIT" ? "positive" : nextAction === "REVIEW_UPDATED_ASSESSMENT" || nextAction === "RESOLVE_EVIDENCE" ? "attention" : ""}`} aria-labelledby="campaign-next-title">
        <div className="campaign-focus-icon" aria-hidden="true">{nextAction === "READY_TO_SUBMIT" ? "✓" : nextAction === "AWAITING_APPROVAL" ? "…" : "→"}</div>
        <div className="campaign-next-copy">
          <span className="campaign-kicker">ESTADO DA CAMPANHA</span>
          <h2 id="campaign-next-title">{stateTitle}</h2>
          <p>{nextAction === "NONE" ? (lockMessage ?? "Nenhuma ação principal necessária neste momento.") : actionHelp[nextAction] ?? "Consulte a preparação abaixo para ver os detalhes."}</p>
          {candidateAssessmentBlocker && <p className="campaign-context-warning">A análise comercial mudou depois da criação desta campanha.</p>}
          {evidenceBlocker && <p className="campaign-context-warning">A estratégia pode ser salva, mas a análise editorial continua sendo a fonte de decisão.</p>}
          {submitMessage && <p role="status" className="campaign-status-message">{submitMessage}</p>}
          {submitError && <p role="alert" className="inline-error">{submitError}</p>}
          {nextAction === "READY_TO_SUBMIT" && editable && <button type="button" className="primary-button" disabled={submitBusy || strategyDirty || commercialDirty} onClick={submitCampaign}>{submitBusy ? "Enviando…" : "Enviar para aprovação"}</button>}
          {(nextAction === "REVIEW_UPDATED_ASSESSMENT" || nextAction === "RESOLVE_EVIDENCE") && <Link className="primary-button" to={`/curator/${c.candidateId}`}>{nextAction === "REVIEW_UPDATED_ASSESSMENT" ? "Revisar oportunidade" : "Abrir oportunidade"}</Link>}
          {anchorForAction[nextAction] && <button type="button" className="primary-button" onClick={goToNextAction}>{nextActionTitle}</button>}
          {nextAction === "AWAITING_APPROVAL" && <Badge tone="warning">Aguardando decisão humana</Badge>}
          {nextAction === "NONE" && c.status === "APPROVED" && <p className="campaign-muted-note">Esta tela não cria conteúdo, publica nem autoriza gastos.</p>}
        </div>
      </section>

      <section className="campaign-readiness panel" aria-labelledby="campaign-readiness-title">
        <div className="campaign-panel-heading">
          <div><span className="campaign-kicker">PREPARAÇÃO</span><h2 id="campaign-readiness-title">{ready.state === "READY_FOR_APPROVAL" ? "Todos os requisitos atendidos" : ready.state === "PENDING_APPROVAL" ? "Requisitos da campanha" : label(ready.state)}</h2></div>
          <Badge tone={ready.state === "READY_FOR_APPROVAL" ? "success" : ready.state === "PENDING_APPROVAL" ? "warning" : statusTone(ready.state)}>{passedCount} de {checkEntries.length} requisitos atendidos</Badge>
        </div>
        {ready.state === "READY_FOR_APPROVAL" && <p className="campaign-ready-message">A Campaign está pronta para decisão humana. Nenhuma aprovação foi criada automaticamente.</p>}
        {!!blockers.length && <div className="campaign-blockers"><h3>{blockers.length} {blockers.length === 1 ? "pendência" : "pendências"}</h3><ul>{blockers.map((item) => <li key={item.code}>{item.message || label(item.code)}</li>)}</ul></div>}
        {candidateAssessmentBlocker && <p className="campaign-context-warning">A análise comercial mudou depois da criação desta campanha. A Campaign não será atualizada automaticamente.</p>}
        {evidenceBlocker && <p className="campaign-context-warning">A análise editorial ainda impede o envio; preencher a estratégia não contorna esse bloqueio.</p>}
        <div className="campaign-check-groups">{readinessGroups.map((group) => <section key={group.title} aria-label={group.title}><h3>{group.title}</h3><ul>{group.keys.map((key) => key in checks && <li key={key} className={checks[key] ? "met" : "missing"}><span aria-hidden="true">{checks[key] ? "✓" : "○"}</span><span>{label(key)}</span><b>{checks[key] ? "Atendido" : "Pendente"}</b></li>)}</ul></section>)}</div>
        {!!warnings.length && <aside className="campaign-warnings" role="note"><b>Atenção</b>{warnings.map((warning) => <p key={warning.code}>{warning.message || label(warning.code)}</p>)}</aside>}
      </section>
    </div>

    <div className="campaign-main-grid">
      <section className={`panel campaign-strategy ${nextAction === "COMPLETE_STRATEGY" ? "is-highlighted" : ""}`} id="campaign-strategy" tabIndex={-1}>
        <div className="campaign-panel-heading"><div><span className="campaign-kicker">MENSAGEM E PÚBLICO</span><h2>Estratégia editorial</h2></div>{editable && strategyDirty && <Badge tone="warning">Alterações não salvas</Badge>}</div>
        {editable ? <form className="campaign-strategy-form" onSubmit={saveStrategy}>
          <label>Objetivo<select value={strategyDraft.objective} onChange={(event) => strategySet("objective", event.target.value)}>{["CONVERSION", "TRAFFIC", "DISCOVERY", "PRICE_ALERT", "EDUCATION", "COMPARISON"].map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>
          <label className="wide">Público<input value={strategyDraft.audience} maxLength={2000} onChange={(event) => strategySet("audience", event.target.value)} placeholder="Para quem esta campanha é relevante?" /></label>
          <label className="wide">Posicionamento<textarea value={strategyDraft.positioning} maxLength={2000} onChange={(event) => strategySet("positioning", event.target.value)} placeholder="Como a campanha deve abordar o produto?" /></label>
          <label className="wide">Mensagem principal<textarea value={strategyDraft.message} maxLength={2000} onChange={(event) => strategySet("message", event.target.value)} placeholder="Qual é a mensagem central?" /></label>
          <label>Chamada para ação<input value={strategyDraft.cta} maxLength={1000} onChange={(event) => strategySet("cta", event.target.value)} placeholder="Ex.: Confira os detalhes" /></label>
          <label className="wide">Disclosure<textarea value={strategyDraft.disclosure} maxLength={2000} onChange={(event) => strategySet("disclosure", event.target.value)} /></label>
          {strategyDirty && <div className="campaign-form-actions"><button type="submit" className="secondary-button" disabled={strategySaving}>{strategySaving ? "Salvando…" : "Salvar estratégia"}</button><span role="status">{strategyMessage}</span></div>}
          {!strategyDirty && strategyMessage && <p className="campaign-inline-status" role="status">{strategyMessage}</p>}
        </form> : <dl className="campaign-readonly-fields"><div><dt>Objetivo</dt><dd>{label(c.objective)}</dd></div><div><dt>Público</dt><dd>{c.targetAudience || "Não informado"}</dd></div><div><dt>Posicionamento</dt><dd>{c.editorialPositioning || "Não informado"}</dd></div><div><dt>Mensagem principal</dt><dd>{c.primaryMessage || "Não informado"}</dd></div><div><dt>Chamada para ação</dt><dd>{c.ctaStrategy || "Não informado"}</dd></div></dl>}
      </section>

      <section className={`panel campaign-destination ${["CONFIGURE_AFFILIATE_LINK", "VERIFY_AFFILIATE_LINK"].includes(nextAction) ? "is-highlighted" : ""}`} id="campaign-destination" tabIndex={-1}>
        <div className="campaign-panel-heading"><div><span className="campaign-kicker">OFERTA E ATRIBUIÇÃO</span><h2>Destino comercial</h2></div></div>
        <div className="campaign-link-source"><h3>Oferta na Curadoria</h3><p>Este é o vínculo do candidato de origem. A URL usada na aprovação é configurada abaixo, nesta Campaign.</p><AffiliateDestination candidateId={c.candidateId} readOnly={locked} secondaryAction /></div>
        <form className="campaign-destination-form" onSubmit={saveCommercial}>
          <h3>Link desta Campaign</h3>
          {editable ? <>
            <label>Link de afiliado<input type="url" value={commercialDraft.url} maxLength={2000} onChange={(event) => commercialSet("url", event.target.value)} placeholder="https://…" /></label>
            <label className="campaign-verified-control"><input type="checkbox" checked={commercialDraft.verified} onChange={(event) => commercialSet("verified", event.target.checked)} /> Marcar como verificado</label>
            <p className="campaign-field-hint">Marque somente após conferir o destino e a oferta. A validade e verificação são exigidas pela preparação da Campaign conforme o objetivo.</p>
            {commercialDirty && <div className="campaign-form-actions"><button type="submit" className="secondary-button" disabled={commercialSaving}>{commercialSaving ? "Salvando…" : "Salvar destino"}</button><span role="status">{commercialMessage}</span></div>}
            {!commercialDirty && commercialMessage && <p className="campaign-inline-status" role="status">{commercialMessage}</p>}
          </> : <div className="campaign-link-readonly"><span><small>Link</small>{c.affiliateUrl ? <a href={c.affiliateUrl} target="_blank" rel="noreferrer">Abrir link configurado</a> : <b>Não configurado</b>}</span><span><small>Verificação</small><b>{c.affiliateUrl ? label(c.affiliateUrlVerifiedAt ? "VERIFIED" : "UNVERIFIED") : "Não aplicável"}</b></span></div>}
        </form>
      </section>
    </div>

    <section className="campaign-execution" aria-label="Execução editorial">
      <section className={`panel ${nextAction === "ADD_CHANNEL" ? "is-highlighted" : ""}`} id="campaign-channels" tabIndex={-1}>
        <div className="campaign-panel-heading"><div><span className="campaign-kicker">DISTRIBUIÇÃO</span><h2>Canais</h2></div><Badge>{ready.channelCount} ativos</Badge></div>
        {channels.length ? <ul className="campaign-item-list">{channels.map((item) => <li key={item.id}><span><b>{label(item.channel)}</b><small>{item.enabled ? "Ativo" : "Desativado"} · {label(item.publicationMode)}</small></span>{item.enabled && <Badge tone="success">Habilitado</Badge>}</li>)}</ul> : <Empty>Nenhum canal configurado.</Empty>}
        {editable && <form className="campaign-add-form" onSubmit={(event) => { event.preventDefault(); void runChildAction("channel", () => campaignsApi.addChannel(id, { channel: channelDraft, enabled: true, publicationMode: "MANUAL" }), () => setChannelDraft("TIKTOK")); }}><label>Adicionar canal<select value={channelDraft} onChange={(event) => setChannelDraft(event.target.value)}>{["TIKTOK", "INSTAGRAM_REELS", "YOUTUBE_SHORTS", "FACEBOOK_REELS", "WHATSAPP", "WEBSITE"].filter((value) => !existingChannels.has(value)).map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label><button type="submit" className="secondary-button" disabled={!!childBusy || !["TIKTOK", "INSTAGRAM_REELS", "YOUTUBE_SHORTS", "FACEBOOK_REELS", "WHATSAPP", "WEBSITE"].some((value) => !existingChannels.has(value))}>{childBusy === "channel" ? "Adicionando…" : "Adicionar canal"}</button></form>}
      </section>

      <section className={`panel ${nextAction === "ADD_ANGLE" ? "is-highlighted" : ""}`} id="campaign-angles" tabIndex={-1}>
        <div className="campaign-panel-heading"><div><span className="campaign-kicker">ABORDAGEM EDITORIAL</span><h2>Ângulos</h2></div><Badge>{ready.angleCount} ativos</Badge></div>
        {angles.length ? <ul className="campaign-item-list">{angles.map((item) => <li key={item.id} className="campaign-angle-item"><span><b>{item.title}</b><small>{label(item.angleType)} · {label(item.status)}</small><p>{item.premise}</p>{item.targetSegment && <small>Público: {item.targetSegment}</small>}</span></li>)}</ul> : <Empty>Nenhum ângulo editorial configurado.</Empty>}
        {editable && <form className="campaign-add-form campaign-angle-form" onSubmit={(event) => { event.preventDefault(); void runChildAction("angle", () => campaignsApi.addAngle(id, { angleType: angleDraft.type, title: angleDraft.title, premise: angleDraft.premise }), () => setAngleDraft({ type: "SMART_BUYING", title: "", premise: "" })); }}><label>Tipo<select value={angleDraft.type} onChange={(event) => setAngleDraft({ ...angleDraft, type: event.target.value })}>{["SMART_BUYING", "OPPORTUNITY", "DISCOVERY", "COMPARISON", "PROBLEM_SOLUTION", "PRICE_ALERT", "REVIEW", "LIMITATION_FIRST", "EDUCATION"].map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label><label>Título<input value={angleDraft.title} maxLength={200} required onChange={(event) => setAngleDraft({ ...angleDraft, title: event.target.value })} /></label><label className="wide">Premissa<textarea value={angleDraft.premise} required onChange={(event) => setAngleDraft({ ...angleDraft, premise: event.target.value })} /></label><button type="submit" className="secondary-button" disabled={!!childBusy}>{childBusy === "angle" ? "Adicionando…" : "Adicionar ângulo"}</button></form>}
      </section>

      <section className={`panel ${nextAction === "ADD_EXPERIMENT" ? "is-highlighted" : ""}`} id="campaign-experiments" tabIndex={-1}>
        <div className="campaign-panel-heading"><div><span className="campaign-kicker">APRENDIZADO EDITORIAL</span><h2>Experimentos</h2></div><Badge>{ready.experimentCount} válidos</Badge></div>
        {experiments.length ? <ul className="campaign-item-list">{experiments.map((item) => <li key={item.id}><span><b>{item.hypothesis}</b><small>{label(item.status)}{item.targetChannel ? ` · ${label(item.targetChannel)}` : " · Todos os canais"}</small>{item.angleId && <small>Ângulo: {angleTitles.get(item.angleId) ?? "Ângulo não disponível"}</small>}{(item.hookStrategy || item.ctaStrategy) && <p>{[item.hookStrategy && `Hook: ${item.hookStrategy}`, item.ctaStrategy && `${label("CTA")}: ${item.ctaStrategy}`].filter(Boolean).join(" · ")}</p>}</span></li>)}</ul> : <Empty>Nenhum experimento configurado.</Empty>}
        {editable && <form className="campaign-add-form campaign-experiment-form" onSubmit={(event) => { event.preventDefault(); void runChildAction("experiment", () => campaignsApi.addExperiment(id, { angleId: experimentDraft.angleId || null, hypothesis: experimentDraft.hypothesis, hookStrategy: experimentDraft.hook || null, ctaStrategy: experimentDraft.cta || null, targetChannel: experimentDraft.channel || null }), () => setExperimentDraft({ angleId: "", hypothesis: "", hook: "", cta: "", channel: "" })); }}><label>Ângulo<select value={experimentDraft.angleId} onChange={(event) => setExperimentDraft({ ...experimentDraft, angleId: event.target.value })}><option value="">Sem ângulo</option>{angles.map((angle) => <option key={angle.id} value={angle.id}>{angle.title}</option>)}</select></label><label className="wide">Hipótese<input value={experimentDraft.hypothesis} required onChange={(event) => setExperimentDraft({ ...experimentDraft, hypothesis: event.target.value })} placeholder="O que este experimento pretende aprender?" /></label><label>Hook<input value={experimentDraft.hook} onChange={(event) => setExperimentDraft({ ...experimentDraft, hook: event.target.value })} /></label><label>{label("CTA")}<input value={experimentDraft.cta} onChange={(event) => setExperimentDraft({ ...experimentDraft, cta: event.target.value })} /></label><label>Canal<select value={experimentDraft.channel} onChange={(event) => setExperimentDraft({ ...experimentDraft, channel: event.target.value })}><option value="">Todos os canais</option>{channels.filter((channel) => channel.enabled).map((channel) => <option key={channel.id} value={channel.channel}>{label(channel.channel)}</option>)}</select></label><button type="submit" className="secondary-button" disabled={!!childBusy}>{childBusy === "experiment" ? "Adicionando…" : "Adicionar experimento"}</button></form>}
      </section>
    </section>
    {childError && <p className="campaign-child-error" role="alert">{childError}</p>}

    <section className="panel campaign-compliance">
      <div className="campaign-panel-heading"><div><span className="campaign-kicker">LIMITES EDITORIAIS</span><h2>Compliance</h2></div></div>
      <div className="campaign-compliance-grid"><section><h3>Disclosure obrigatório</h3>{editable ? <p>{c.disclosureText ? "Texto configurado na estratégia editorial." : "Ainda não informado na estratégia editorial."}</p> : <p>{c.disclosureText || "Não informado"}</p>}{distinctRequiredDisclosures.length > 0 && <ul>{distinctRequiredDisclosures.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>}</section><section><h3>Advertências</h3>{c.requiredWarnings.length ? <ul>{c.requiredWarnings.map((item) => <li key={item.code}>{item.message || label(item.code)}</li>)}</ul> : <p>Nenhuma advertência registrada.</p>}</section><section><h3>{label("Claims proibidos")}</h3>{c.forbiddenClaims.length ? <div className="campaign-claim-list">{c.forbiddenClaims.map((item) => <Badge key={item} tone="warning">{label(item)}</Badge>)}</div> : <p>Nenhuma alegação proibida registrada.</p>}</section></div>
    </section>
  </main>;
}

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CampaignPage } from "../pages/Campaigns";
import type { Campaign, CampaignReadiness } from "../types";

const baseCampaign: Campaign = {
  id: "campaign-1", candidateId: "candidate-1", assessmentId: "assessment-1", name: "Parafusadeira doméstica",
  status: "DRAFT", objective: "EDUCATION", editorialVerdictSnapshot: "WORTH_IT", trustGateSnapshot: "PASS",
  recommendationScoreSnapshot: 72, opportunityScoreSnapshot: 81, priceVerdictSnapshot: "GOOD_PRICE", campaignPriority: "HIGH",
  targetAudience: "Pessoas que fazem pequenos reparos em casa", editorialPositioning: "Uma escolha para tarefas domésticas",
  primaryMessage: "Avalie se atende aos seus projetos", affiliateUrl: null, affiliateUrlSource: "MANUAL", affiliateUrlVerifiedAt: null,
  disclosureText: "Este conteúdo pode conter links de afiliado.", ctaStrategy: "Confira os detalhes", requiresFinancialSpend: false,
  trustWarningsSnapshot: [], requiredDisclosures: ["Informe a relação de afiliado"], requiredWarnings: [{ code: "FINANCIAL_APPROVAL_REQUIRED", message: "Gastos exigem autorização separada." }],
  forbiddenClaims: ["BEST_ON_MARKET_UNSUPPORTED"], createdAt: "2026-09-01T12:00:00Z", updatedAt: "2026-09-02T12:00:00Z", approvedAt: null, rejectedAt: null,
};
const allChecks = {
  assessment: true, sourceAssessmentCurrent: true, trustGate: true, editorialVerdict: true,
  targetAudience: true, editorialPositioning: true, primaryMessage: true, cta: true,
  affiliateLink: true, affiliateLinkVerified: true, disclosure: true, channel: true, angle: true, experiment: true,
};
const readiness = (nextAction: string, state = "NOT_READY", checks: Record<string, boolean> = { ...allChecks, channel: false }, blockers: CampaignReadiness["blockers"] = [{ code: "CHANNEL_REQUIRED", message: "Adicione um canal habilitado." }]): CampaignReadiness => ({
  state, campaignStatus: baseCampaign.status, checks, blockers, warnings: [{ code: "FINANCIAL_APPROVAL_REQUIRED", message: "Gastos exigem autorização separada." }], nextAction,
  channelCount: 1, angleCount: 1, experimentCount: 1,
});
const channel = { id: "channel-1", campaignId: "campaign-1", channel: "INSTAGRAM_REELS", enabled: true, publicationMode: "MANUAL", platformNotes: null };
const angle = { id: "angle-1", campaignId: "campaign-1", angleType: "HOME_USE", title: "Uso doméstico", premise: "Foco em pequenos reparos", targetSegment: null, priority: 1, status: "ACTIVE" };
const experiment = { id: "experiment-1", campaignId: "campaign-1", angleId: "angle-1", hypothesis: "Uma abordagem educativa aumenta a confiança", status: "PLANNED", hookStrategy: "Comece pelo uso", ctaStrategy: "Confira os detalhes", targetChannel: "INSTAGRAM_REELS", variantGroup: null };
const destination = { candidateId: "candidate-1", productTitle: "Parafusadeira doméstica", sourcePermalink: null, expectedItemId: null, affiliateUrl: null, affiliateUrlSource: null, affiliateValidationStatus: "UNKNOWN", affiliateItemId: null, destinationUrl: null, destinationStrategy: "DIRECT_AFFILIATE_LINK", failureCode: null };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function setup(options: { campaign?: Partial<Campaign>; ready?: CampaignReadiness; onSubmit?: () => Promise<void> } = {}) {
  let campaign = { ...baseCampaign, ...options.campaign };
  let currentReadiness = options.ready ?? readiness("COMPLETE_STRATEGY");
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/campaigns/campaign-1/submit-for-approval") && init?.method === "POST") {
      await options.onSubmit?.();
      campaign = { ...campaign, status: "PENDING_APPROVAL" };
      currentReadiness = readiness("AWAITING_APPROVAL", "PENDING_APPROVAL", allChecks, []);
      return json({ id: "approval-1" });
    }
    if (url.endsWith("/campaigns/campaign-1/readiness")) return json({ ...currentReadiness, campaignStatus: campaign.status });
    if (url.endsWith("/campaigns/campaign-1/channels")) return json([channel]);
    if (url.endsWith("/campaigns/campaign-1/angles")) return json([angle]);
    if (url.endsWith("/campaigns/campaign-1/experiments")) return json([experiment]);
    if (url.includes("/campaigns/campaign-1/creative-handoff")) return json({ state: campaign.status === "APPROVED" ? "READY_TO_CREATE" : "NOT_ELIGIBLE", campaignId: "campaign-1", campaignStatus: campaign.status, approvalId: null, assessmentId: "assessment-1", experimentId: null, creativeId: null, creativeName: null, creativeStatus: null, targetChannel: campaign.status === "APPROVED" ? "INSTAGRAM_REELS" : null, reasonCode: campaign.status === "APPROVED" ? null : "CAMPAIGN_NOT_APPROVED" });
    if (url.endsWith("/campaigns/campaign-1") && init?.method === "PATCH") {
      campaign = { ...campaign, ...JSON.parse(String(init.body)) };
      currentReadiness = readiness("ADD_CHANNEL", "NOT_READY", { ...allChecks, channel: false });
      return json(campaign);
    }
    if (url.endsWith("/campaigns/campaign-1")) return json(campaign);
    if (url.endsWith("/candidates/candidate-1/affiliate-destination")) return json(destination);
    throw new Error(`Unexpected HTTP request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/campanhas/campaign-1"]}><Routes><Route path="/campanhas/:id" element={<CampaignPage />} /><Route path="/curator/:id" element={<div>Curadoria da oportunidade</div>} /></Routes></MemoryRouter>);
  return fetchMock;
}
const submitRequests = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.filter(([url, init]) => String(url).endsWith("/submit-for-approval") && (init as RequestInit | undefined)?.method === "POST");

afterEach(() => vi.unstubAllGlobals());

describe("Campaign Workspace", () => {
  it("explica blockers em linguagem humana sem expor o código interno", async () => {
    setup({ ready: readiness("COMPLETE_STRATEGY", "NOT_READY", { ...allChecks, targetAudience: false }, [{ code: "TARGET_AUDIENCE_REQUIRED", message: "Defina o público-alvo." }]) });
    expect(await screen.findByText("Defina o público-alvo.")).toBeInTheDocument();
    expect(screen.queryByText("TARGET_AUDIENCE_REQUIRED")).not.toBeInTheDocument();
    expect(screen.getByText("Pendente", { selector: "b" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Completar estratégia" })).toBeInTheDocument();
  });

  it.each([["ADD_CHANNEL", "Adicionar canal", "campaign-channels"], ["ADD_ANGLE", "Adicionar ângulo", "campaign-angles"], ["ADD_EXPERIMENT", "Adicionar experimento", "campaign-experiments"]])("destaca a seção da próxima ação %s", async (nextAction, title, id) => {
    setup({ ready: readiness(nextAction) });
    expect((await screen.findAllByRole("button", { name: title })).length).toBeGreaterThan(1);
    expect(document.getElementById(id)).toHaveClass("is-highlighted");
    expect(document.querySelectorAll(".campaign-focus-grid .primary-button")).toHaveLength(1);
  });

  it("READY_TO_SUBMIT não envia automaticamente e bloqueia duplo clique", async () => {
    let finishSubmit!: () => void;
    const onSubmit = vi.fn(() => new Promise<void>((resolve) => { finishSubmit = resolve; }));
    const mock = setup({ ready: readiness("READY_TO_SUBMIT", "READY_FOR_APPROVAL", allChecks, []), onSubmit });
    const button = await screen.findByRole("button", { name: "Enviar para aprovação" });
    expect(submitRequests(mock)).toHaveLength(0);
    fireEvent.click(button);
    fireEvent.click(button);
    expect(await screen.findByRole("button", { name: "Enviando…" })).toBeDisabled();
    expect(submitRequests(mock)).toHaveLength(1);
    finishSubmit();
    expect(await screen.findByText("Campaign enviada para aprovação.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Enviar para aprovação" })).not.toBeInTheDocument());
    expect(screen.getAllByText("Aguardando aprovação").length).toBeGreaterThan(0);
  });

  it.each(["PENDING_APPROVAL", "APPROVED", "PAUSED", "ARCHIVED"]) ("mantém %s somente para leitura", async (status) => {
    setup({ campaign: { status }, ready: readiness(status === "PENDING_APPROVAL" ? "AWAITING_APPROVAL" : "NONE", status, allChecks, []) });
    await screen.findByRole("heading", { name: "Parafusadeira doméstica" });
    expect(screen.queryByLabelText("Público")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Salvar estratégia" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adicionar canal" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adicionar ângulo" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adicionar experimento" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Enviar para aprovação" })).not.toBeInTheDocument();
    if (status === "PENDING_APPROVAL") expect(screen.getByText("O conteúdo permanece bloqueado até a decisão humana.")).toBeInTheDocument();
  });

  it("evita repetir Aguardando aprovação no bloco de preparação e mostra disclosure uma única vez", async () => {
    setup({ campaign: { status: "PENDING_APPROVAL" }, ready: readiness("AWAITING_APPROVAL", "PENDING_APPROVAL", allChecks, []) });
    await screen.findByRole("heading", { name: "Parafusadeira doméstica" });
    expect(screen.getAllByText("Aguardando aprovação")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "Requisitos da campanha" })).toBeInTheDocument();
    expect(screen.getByText("14 de 14 requisitos atendidos")).toBeInTheDocument();
    expect(screen.getAllByText(baseCampaign.disclosureText)).toHaveLength(1);
  });

  it.each(["DRAFT", "REJECTED"]) ("mantém %s editável", async (status) => {
    setup({ campaign: { status }, ready: readiness("COMPLETE_STRATEGY") });
    expect(await screen.findByLabelText("Público")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Adicionar canal" })).toBeInTheDocument();
  });

  it("encaminha blockers de análise para a Curadoria e não recomenda corrigir a estratégia", async () => {
    setup({ ready: readiness("REVIEW_UPDATED_ASSESSMENT", "NOT_READY", allChecks, [{ code: "ASSESSMENT_OUTDATED", message: "A análise precisa ser revisada." }]) });
    expect(await screen.findByRole("link", { name: "Revisar oportunidade" })).toHaveAttribute("href", "/curator/candidate-1");
    expect(screen.getByText("A análise comercial mudou depois da criação desta campanha.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Completar estratégia" })).not.toBeInTheDocument();
  });

  it("evidência insuficiente direciona para a oportunidade, não para completar estratégia", async () => {
    setup({ ready: readiness("RESOLVE_EVIDENCE", "NOT_READY", allChecks, [{ code: "TRUST_GATE_BLOCKED", message: "A análise editorial ainda não tem evidências suficientes." }]) });
    expect(await screen.findByRole("link", { name: "Abrir oportunidade" })).toHaveAttribute("href", "/curator/candidate-1");
    expect(screen.getByText("A análise editorial ainda impede o envio; preencher a estratégia não contorna esse bloqueio.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Completar estratégia" })).not.toBeInTheDocument();
  });

  it("mostra warnings separados dos blockers e não trata aprovação financeira como erro", async () => {
    setup({ ready: readiness("NONE") });
    await waitFor(() => expect(document.querySelector(".campaign-warnings")).toBeInTheDocument());
    const warnings = document.querySelector(".campaign-warnings") as HTMLElement;
    expect(within(warnings).getByText("Gastos exigem autorização separada.")).toBeInTheDocument();
    expect(warnings).toHaveTextContent("Atenção");
    expect(screen.queryByRole("alert", { name: /Gastos exigem/ })).not.toBeInTheDocument();
  });

  it("salva estratégia e recarrega Campaign e readiness", async () => {
    const mock = setup({ ready: readiness("COMPLETE_STRATEGY") });
    const audience = await screen.findByLabelText("Público");
    await waitFor(() => expect(audience).toHaveValue(baseCampaign.targetAudience));
    fireEvent.change(audience, { target: { value: "Público atualizado" } });
    fireEvent.click(await screen.findByRole("button", { name: "Salvar estratégia" }));
    await waitFor(() => expect(mock).toHaveBeenCalledWith(expect.stringMatching(/\/campaigns\/campaign-1$/), expect.objectContaining({ method: "PATCH" })));
    expect(await screen.findByText("Estratégia salva. Preparação atualizada.")).toBeInTheDocument();
    const readinessGets = mock.mock.calls.filter(([url]) => String(url).endsWith("/campaigns/campaign-1/readiness"));
    expect(readinessGets.length).toBeGreaterThan(1);
  });

  it("exibe filhos editoriais e resolve o título do ângulo sem requisição por experimento", async () => {
    const mock = setup();
    expect((await screen.findAllByText("Instagram Reels")).length).toBeGreaterThan(0);
    const items = document.querySelector(".campaign-execution");
    expect(within(items as HTMLElement).getByText("Uma abordagem educativa aumenta a confiança")).toBeInTheDocument();
    expect(screen.getByText("Ângulo: Uso doméstico")).toBeInTheDocument();
    expect(mock.mock.calls.some(([url]) => String(url).includes("/experiments/experiment-1"))).toBe(false);
  });

  it("mantém compliance visível, apresenta IDs apenas em detalhes recolhíveis e layout sem larguras fixas", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: "Compliance" })).toBeInTheDocument();
    expect(screen.getByText("Disclosure obrigatório")).toBeInTheDocument();
    expect(screen.getByText("Melhor do mercado sem evidência")).toBeInTheDocument();
    const heroMetrics = document.querySelector(".campaign-hero-meta") as HTMLElement;
    expect(within(heroMetrics).getByText("Recomendação")).toBeInTheDocument();
    expect(within(heroMetrics).getByText("Oportunidade")).toBeInTheDocument();
    expect(screen.getByText("Alegações proibidas")).toBeInTheDocument();
    expect(document.querySelector(".campaign-execution")).toHaveTextContent("Planejado");
    const details = screen.getByText("Detalhes técnicos e origem").closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(document.querySelector(".campaign-execution")).toBeInTheDocument();
    expect(document.querySelector(".campaign-workspace" )).toBeInTheDocument();
  });
});

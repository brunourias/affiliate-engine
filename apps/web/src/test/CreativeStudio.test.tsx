import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";

const campaign = { id: "cp1", name: "Parafusadeira doméstica", status: "APPROVED" };
const creative = { id: "cr1", campaignId: "cp1", experimentId: null, name: "Criativo — Produto", status: "DRAFT", contentType: "SHORT_VIDEO", targetChannel: "GENERIC", angleTypeSnapshot: null, objectiveSnapshot: "EDUCATION", editorialVerdictSnapshot: "WORTH_IT", priceVerdictSnapshot: "FAIR_PRICE", title: null, contentPremise: null, hook: "Vale a pena?", bodyScript: "Texto", cta: "Compare", estimatedDurationSeconds: 20, disclosureText: "Afiliado", requiredWarnings: [], forbiddenClaims: ["BEST_ON_MARKET_UNSUPPORTED", "LOWEST_PRICE_UNVERIFIED", "NO_DEFECTS_CLAIM", "ONE_HUNDRED_PERCENT_RECOMMENDED", "OWN_TEST_CLAIM", "PRICE_PROMOTION_CLAIM", "BUY_NOW_CTA"], generationMode: "MANUAL", variantGroup: null, parentCreativeId: null, variantLabel: null, creationSource: null, creationKey: null, sourceCampaignApprovalId: null, sourceAssessmentId: null };
function response(body: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })); }
const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
  const url = String(input); const method = init?.method ?? "GET";
  if (url.endsWith("/creatives")) return response([creative]);
  if (url.endsWith("/creatives/cr1/scenes")) return response([]);
  if (url.endsWith("/creatives/cr1/readiness")) return response({ state: "NOT_READY", checks: {}, sceneCount: 0, compliance: { status: "PASS", reasons: [], requiredWarningCoverage: [] } });
  if (url.endsWith("/creatives/cr1/generate-template") && method === "POST") return response({ ...creative, title: "Parafusadeira para uso doméstico", contentPremise: "Uso doméstico", hook: "Vale a pena considerar esta parafusadeira?", bodyScript: "Roteiro coerente com as cenas.", cta: "Compare os detalhes", estimatedDurationSeconds: 20, generationMode: "DETERMINISTIC_TEMPLATE" });
  if (url.endsWith("/creatives/cr1")) return response(creative);
  if (url.endsWith("/campaigns/cp1")) return response(campaign);
  if (url.endsWith("/campaigns/cp1/channels")) return response([]);
  if (url.endsWith("/campaigns/cp1/angles")) return response([]);
  if (url.endsWith("/campaigns/cp1/experiments")) return response([]);
  if (url.endsWith("/campaigns/cp1/readiness")) return response({ state: "APPROVED", checks: {}, blockers: [], warnings: [], nextAction: "NONE", channelCount: 0, angleCount: 0, experimentCount: 0 });
  if (url.includes("/campaigns/cp1/creative-handoff")) return response({ state: "NOT_ELIGIBLE", campaignId: "cp1", campaignStatus: "APPROVED", approvalId: null, assessmentId: null, experimentId: null, creativeId: null, creativeName: null, creativeStatus: null, targetChannel: null, reasonCode: "CAMPAIGN_APPROVAL_REQUIRED" });
  if (url.endsWith("/candidates/candidate1/affiliate-destination")) return response({ candidateId: "candidate1", productTitle: null, sourcePermalink: null, expectedItemId: null, affiliateUrl: null, affiliateUrlSource: null, affiliateValidationStatus: "UNKNOWN", affiliateItemId: null, destinationUrl: null, destinationStrategy: "DIRECT_AFFILIATE_LINK", failureCode: null });
  return response([]);
});
beforeEach(() => vi.stubGlobal("fetch", fetchMock));
afterEach(() => { vi.unstubAllGlobals(); fetchMock.mockClear(); });

async function at(path: string) { window.history.pushState({}, "", path); window.dispatchEvent(new PopStateEvent("popstate")); return render(<App />); }

describe("Creative Studio", () => {
  it("lista e edita draft controlado sem render/publicação", async () => {
    await at("/criativos");
    expect(await screen.findByText("Criativo — Produto")).toBeInTheDocument();
    expect(screen.getByText("Rascunho")).toBeInTheDocument();
    expect(screen.getByText(/Vídeo curto · Genérico/)).toBeInTheDocument();
    await act(async () => { window.history.pushState({}, "", "/criativos/cr1"); window.dispatchEvent(new PopStateEvent("popstate")); });
    expect(await screen.findByText("Parafusadeira doméstica")).toBeInTheDocument();
    expect(screen.queryByText("cp1")).not.toBeInTheDocument();
    expect(screen.getByText("Sem ângulo definido")).toBeInTheDocument();
    expect(screen.getByText("Melhor do mercado sem evidência")).toBeInTheDocument();
    expect(screen.getByText("Menor preço não verificado")).toBeInTheDocument();
    expect(screen.getByText("Alegação de ausência de defeitos")).toBeInTheDocument();
    expect(screen.getByText("Recomendação 100% não permitida")).toBeInTheDocument();
    expect(screen.getByText("Alegação de teste próprio")).toBeInTheDocument();
    expect(screen.getByText("Alegação promocional de preço")).toBeInTheDocument();
    expect(screen.getByText("CTA de compra imediata")).toBeInTheDocument();
    const hook = await screen.findByDisplayValue("Vale a pena?");
    fireEvent.change(hook, { target: { value: "Novo hook" } });
    expect(hook).toHaveValue("Novo hook");
    expect(screen.getByText("Não salvo")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /publicar|renderizar/i })).not.toBeInTheDocument();
  });

  it("atualiza campos principais ao gerar estrutura inicial", async () => {
    vi.stubGlobal("confirm", vi.fn(() => true));
    await at("/criativos/cr1");
    fireEvent.click(await screen.findByRole("button", { name: "Gerar estrutura inicial" }));
    expect(await screen.findByDisplayValue("Vale a pena considerar esta parafusadeira?")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Roteiro coerente com as cenas.")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Compare os detalhes")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Parafusadeira para uso doméstico")).toBeInTheDocument();
  });
});

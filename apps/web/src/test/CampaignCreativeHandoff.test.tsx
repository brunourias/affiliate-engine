import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CampaignCreativeHandoff } from "../components/CampaignCreativeHandoff";
import type { Campaign, CampaignAngle, CampaignChannel, CampaignExperiment, CreativeHandoffState } from "../types";

const campaign = { id: "c1", candidateId: "candidate1", assessmentId: "assessment1", name: "Campanha teste", status: "APPROVED", requiresFinancialSpend: false } as Campaign;
const channel1 = { id: "ch1", campaignId: "c1", channel: "TIKTOK", enabled: true, publicationMode: "MANUAL", platformNotes: null } satisfies CampaignChannel;
const channel2 = { id: "ch2", campaignId: "c1", channel: "INSTAGRAM_REELS", enabled: true, publicationMode: "MANUAL", platformNotes: null } satisfies CampaignChannel;
const channelDisabled = { id: "ch3", campaignId: "c1", channel: "WEBSITE", enabled: false, publicationMode: "MANUAL", platformNotes: null } satisfies CampaignChannel;
const angle = { id: "a1", campaignId: "c1", angleType: "HOME_USE", title: "Uso doméstico", premise: "Uso informado", targetSegment: null, priority: 1, status: "ACTIVE" } satisfies CampaignAngle;
const experiment = { id: "exp1", campaignId: "c1", angleId: "a1", hypothesis: "Uma abordagem educativa aumenta a confiança", status: "PLANNED", hookStrategy: null, ctaStrategy: null, targetChannel: null, variantGroup: null } satisfies CampaignExperiment;
const fixedExperiment = { ...experiment, targetChannel: "INSTAGRAM_REELS" };
const ready: CreativeHandoffState = { state: "READY_TO_CREATE", campaignId: "c1", campaignStatus: "APPROVED", approvalId: "approval-uuid", assessmentId: "assessment-uuid", experimentId: null, creativeId: null, creativeName: null, creativeStatus: null, targetChannel: "TIKTOK", reasonCode: null };
const exists: CreativeHandoffState = { ...ready, state: "CREATIVE_EXISTS", creativeId: "creative-1", creativeName: "Criativo inicial", creativeStatus: "DRAFT" };
const ineligible = (reasonCode: string, status = "APPROVED"): CreativeHandoffState => ({ ...ready, state: "NOT_ELIGIBLE", campaignStatus: status, targetChannel: null, reasonCode });
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; };
function Location() { return <output data-testid="location">{useLocation().pathname}</output>; }

function setup(options: {
  get?: (url: string, count: number) => Promise<Response> | Response;
  post?: (url: string, init: RequestInit | undefined) => Promise<Response> | Response;
  campaignProps?: Partial<Campaign>;
  experiments?: CampaignExperiment[];
  channels?: CampaignChannel[];
} = {}) {
  let getCount = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/campaigns/c1/creative-handoff")) {
      getCount += 1;
      return options.get ? options.get(url, getCount) : response(ready);
    }
    if (url.endsWith("/creatives/from-campaign/c1") && init?.method === "POST") return options.post ? options.post(url, init) : response({ id: "creative-1" }, 201);
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/campanhas/c1"]}><Location /><CampaignCreativeHandoff campaign={{ ...campaign, ...options.campaignProps }} channels={options.channels ?? [channel1]} angles={[angle]} experiments={options.experiments ?? [experiment]} /></MemoryRouter>);
  return fetchMock;
}
const handoffCalls = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.filter(([url]) => String(url).includes("/creative-handoff"));
const createCalls = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.filter(([url, init]) => String(url).endsWith("/creatives/from-campaign/c1") && (init as RequestInit | undefined)?.method === "POST");

afterEach(() => vi.unstubAllGlobals());

describe("handoff controlado de criativos", () => {
  it("consulta o state do backend e campanha pendente permanece informativa", async () => {
    const mock = setup({ campaignProps: { status: "PENDING_APPROVAL" }, get: () => response(ineligible("CAMPAIGN_NOT_APPROVED", "PENDING_APPROVAL")) });
    expect(await screen.findByText("A criação do criativo ficará disponível após a aprovação humana da campanha.")).toBeInTheDocument();
    expect(screen.getByText("Criação indisponível")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Criar criativo" })).not.toBeInTheDocument();
    expect(handoffCalls(mock)).toHaveLength(1);
  });

  it("não infere elegibilidade pelo status APPROVED quando o backend retorna NOT_ELIGIBLE", async () => {
    const mock = setup({ get: () => response(ineligible("CAMPAIGN_NOT_APPROVED")) });
    expect(await screen.findByText("A campanha ainda não está aprovada para iniciar a criação de um criativo.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Criar criativo" })).not.toBeInTheDocument();
    expect(createCalls(mock)).toHaveLength(0);
  });

  it("READY_TO_CREATE mostra o canal do backend e não cria ao carregar", async () => {
    const mock = setup();
    expect(await screen.findByRole("button", { name: "Criar criativo" })).toBeEnabled();
    expect(screen.getByText("TikTok")).toBeInTheDocument();
    expect(screen.getByText("Campanha aprovada por decisão humana")).toBeInTheDocument();
    expect(screen.getByText(/Não serão geradas cenas, mídia, aprovação ou publicação automaticamente/)).toBeInTheDocument();
    expect(createCalls(mock)).toHaveLength(0);
  });

  it("cria uma vez mesmo em duplo clique, permanece no Workspace e atualiza para CREATIVE_EXISTS", async () => {
    const post = deferred<Response>();
    const mock = setup({ get: (_url, count) => response(count === 1 ? ready : exists), post: () => post.promise });
    const button = await screen.findByRole("button", { name: "Criar criativo" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(await screen.findByRole("button", { name: "Criando…" })).toBeDisabled();
    expect(createCalls(mock)).toHaveLength(1);
    expect(JSON.parse(String((createCalls(mock)[0][1] as RequestInit).body))).toEqual({});
    post.resolve(response({ id: "creative-1" }, 201));
    expect(await screen.findByText("Criativo inicial")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir criativo" })).toHaveAttribute("href", "/criativos/creative-1");
    expect(screen.getByTestId("location")).toHaveTextContent("/campanhas/c1");
    expect(handoffCalls(mock)).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Criar criativo" })).not.toBeInTheDocument();
  });

  it("CREATIVE_EXISTS trata legado normalmente e oferece somente abrir", async () => {
    const mock = setup({ get: () => response(exists) });
    expect(await screen.findByText("Criativo inicial")).toBeInTheDocument();
    expect(screen.getByText("Rascunho")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir criativo" })).toHaveAttribute("href", "/criativos/creative-1");
    expect(screen.queryByRole("button", { name: "Criar criativo" })).not.toBeInTheDocument();
    expect(createCalls(mock)).toHaveLength(0);
  });

  it("MULTIPLE_CREATIVES não escolhe um registro e encaminha para a lista", async () => {
    const mock = setup({ get: () => response({ ...ready, state: "MULTIPLE_CREATIVES", creativeId: null, reasonCode: "MULTIPLE_CREATIVES_FOR_CAMPAIGN" }) });
    expect(await screen.findByText("O sistema não escolherá um automaticamente.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir lista de criativos" })).toHaveAttribute("href", "/criativos");
    expect(screen.queryByRole("button", { name: "Criar criativo" })).not.toBeInTheDocument();
    expect(createCalls(mock)).toHaveLength(0);
  });

  it.each([
    ["CAMPAIGN_APPROVAL_REQUIRED", "A campanha não possui uma aprovação humana válida para esta etapa.", "Ver aprovações", "/aprovacoes"],
    ["CAMPAIGN_APPROVAL_STATE_INCONSISTENT", "O histórico de aprovações desta campanha precisa ser revisado.", "Ver aprovações", "/aprovacoes"],
    ["ASSESSMENT_OUTDATED", "A análise de origem mudou depois da aprovação da campanha.", "Abrir oportunidade", "/curator/candidate1"],
    ["TRUST_GATE_BLOCKED", "A qualidade das evidências não permite iniciar um criativo neste momento.", "Abrir oportunidade", "/curator/candidate1"],
    ["PRIMARY_MESSAGE_REQUIRED", "Defina a mensagem principal da campanha antes de iniciar um criativo.", "Revisar campanha", null],
  ])("apresenta reasonCode %s em português com ação contextual", async (reason, message, action, href) => {
    const mock = setup({ get: () => response(ineligible(reason)) });
    expect(await screen.findByText(new RegExp(message))).toBeInTheDocument();
    const actionElement = screen.getByRole(href ? "link" : "button", { name: action });
    if (href) expect(actionElement).toHaveAttribute("href", href);
    expect(screen.queryByText(reason)).not.toBeInTheDocument();
    expect(createCalls(mock)).toHaveLength(0);
  });

  it("mantém a seleção padrão na campanha base e mostra experimentos com ângulo resolvido localmente", async () => {
    const mock = setup({ get: (_url, count) => response(count === 1 ? ineligible("CREATIVE_TARGET_CHANNEL_REQUIRED") : ready) , channels: [channel1, channelDisabled] });
    expect(await screen.findByLabelText("Origem do criativo")).toHaveValue("");
    expect(screen.getByRole("option", { name: /Uma abordagem educativa aumenta a confiança/ })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Origem do criativo"), { target: { value: "exp1" } });
    await waitFor(() => expect(handoffCalls(mock)).toHaveLength(2));
    expect(String(handoffCalls(mock)[1][0])).toContain("experimentId=exp1");
    expect(await screen.findByText("Uso doméstico")).toBeInTheDocument();
    expect(createCalls(mock)).toHaveLength(0);
  });

  it("desabilita experimentos fora de PLANNED e mostra canal fixo do experimento sem seletor conflitante", async () => {
    setup({ experiments: [fixedExperiment, { ...experiment, id: "old", status: "COMPLETED" }], get: (_url, count) => response(count === 1 ? ready : { ...ready, experimentId: "exp1", targetChannel: "INSTAGRAM_REELS" }) });
    expect(await screen.findByLabelText("Origem do criativo")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Origem do criativo"), { target: { value: "exp1" } });
    expect(await screen.findByText("Instagram Reels")).toBeInTheDocument();
    expect(screen.queryByLabelText("Escolha o canal deste criativo")).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Concluída/i })).toBeDisabled();
  });

  it("seleciona somente canal habilitado, refaz GET e envia targetChannel sem criar ao escolher", async () => {
    const mock = setup({ channels: [channel1, channel2, channelDisabled], get: (_url, count) => response(count === 1 ? ineligible("CREATIVE_TARGET_CHANNEL_REQUIRED") : ready) });
    await screen.findByLabelText("Escolha o canal deste criativo");
    const select = screen.getByLabelText("Escolha o canal deste criativo");
    expect(screen.queryByRole("option", { name: "Site" })).not.toBeInTheDocument();
    fireEvent.change(select, { target: { value: "INSTAGRAM_REELS" } });
    await waitFor(() => expect(handoffCalls(mock)).toHaveLength(2));
    expect(String(handoffCalls(mock)[1][0])).toContain("targetChannel=INSTAGRAM_REELS");
    expect(await screen.findByRole("button", { name: "Criar criativo" })).toBeEnabled();
    expect(createCalls(mock)).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Criar criativo" }));
    await waitFor(() => expect(createCalls(mock)).toHaveLength(1));
    expect(JSON.parse(String((createCalls(mock)[0][1] as RequestInit).body))).toEqual({ targetChannel: "INSTAGRAM_REELS" });
  });

  it("envia experimentId no POST e mostra aviso financeiro sem bloquear", async () => {
    const mock = setup({ campaignProps: { requiresFinancialSpend: true }, get: (_url, count) => response(count === 1 ? ready : { ...ready, experimentId: "exp1" }) });
    expect(await screen.findByText("Esta campanha prevê gasto financeiro. A criação do criativo não autoriza esse gasto.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Origem do criativo"), { target: { value: "exp1" } });
    await waitFor(() => expect(String(handoffCalls(mock)[1][0])).toContain("experimentId=exp1"));
    fireEvent.click(await screen.findByRole("button", { name: "Criar criativo" }));
    await waitFor(() => expect(createCalls(mock)).toHaveLength(1));
    expect(JSON.parse(String((createCalls(mock)[0][1] as RequestInit).body))).toEqual({ experimentId: "exp1" });
  });

  it("após conflito atualiza o state e mostra o vencedor sem retry", async () => {
    const mock = setup({ get: (_url, count) => response(count === 1 ? ready : exists), post: () => response({ detail: { code: "CREATIVE_HANDOFF_CONFLICT", message: "conflito" } }, 409) });
    fireEvent.click(await screen.findByRole("button", { name: "Criar criativo" }));
    expect(await screen.findByText("Este criativo já está disponível.")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Abrir criativo" })).toHaveAttribute("href", "/criativos/creative-1");
    expect(handoffCalls(mock)).toHaveLength(2);
    expect(createCalls(mock)).toHaveLength(1);
  });

  it.each([
    ["CAMPAIGN_CREATIVE_HANDOFF_INVALIDATED", ineligible("ASSESSMENT_OUTDATED"), "A análise de origem mudou depois da aprovação da campanha."],
    ["MULTIPLE_CREATIVES_FOR_CAMPAIGN", { ...ready, state: "MULTIPLE_CREATIVES", reasonCode: "MULTIPLE_CREATIVES_FOR_CAMPAIGN" }, "O sistema não escolherá um automaticamente."],
  ])("atualiza o handoff após conflito %s sem retry automático", async (code, refreshedState, expectedText) => {
    const mock = setup({ get: (_url, count) => response(count === 1 ? ready : refreshedState), post: () => response({ detail: { code, message: "conflito controlado" } }, 409) });
    fireEvent.click(await screen.findByRole("button", { name: "Criar criativo" }));
    expect(await screen.findByText(new RegExp(expectedText))).toBeInTheDocument();
    expect(createCalls(mock)).toHaveLength(1);
    expect(handoffCalls(mock)).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Criar criativo" })).not.toBeInTheDocument();
  });

  it("mantém carregamento dentro do painel e erro com role alert", async () => {
    const pending = deferred<Response>();
    setup({ get: () => pending.promise });
    const panel = screen.getByRole("region", { name: "Criação do criativo" });
    const status = within(panel).getByRole("status");
    expect(status).toHaveTextContent("Verificando próxima etapa…");
    expect(panel).toContainElement(status);
    pending.resolve(response(ineligible("CAMPAIGN_NOT_APPROVED")));
    expect(await screen.findByText("A campanha ainda não está aprovada para iniciar a criação de um criativo.")).toBeInTheDocument();
  });

  it("resposta atrasada de uma seleção antiga não sobrescreve o contexto novo", async () => {
    const stale = deferred<Response>();
    const mock = setup({ get: (url, count) => {
      if (count === 1) return response(ineligible("CAMPAIGN_NOT_APPROVED"));
      if (url.includes("experimentId=exp1")) return stale.promise;
      return response(ready);
    } });
    fireEvent.change(await screen.findByLabelText("Origem do criativo"), { target: { value: "exp1" } });
    fireEvent.change(screen.getByLabelText("Origem do criativo"), { target: { value: "" } });
    expect(await screen.findByRole("button", { name: "Criar criativo" })).toBeEnabled();
    stale.resolve(response(ineligible("EXPERIMENT_NOT_ELIGIBLE")));
    await waitFor(() => expect(screen.getByRole("button", { name: "Criar criativo" })).toBeEnabled());
    expect(String(handoffCalls(mock).at(-1)?.[0])).not.toContain("experimentId=exp1");
  });

  it("não aciona template, aprovação, MediaJob ou publicação e o componente antigo foi removido", async () => {
    const mock = setup();
    await screen.findByRole("button", { name: "Criar criativo" });
    expect(screen.queryByText("Creative Studio")).not.toBeInTheDocument();
    expect(createCalls(mock)).toHaveLength(0);
    expect(mock.mock.calls.some(([url]) => /generate-template|submit-for-review|media-jobs|instagram-publish/.test(String(url)))).toBe(false);
  });
});

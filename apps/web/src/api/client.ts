import type {
  Settings,
  Approval,
  Notification,
  AgentTask,
  Decision,
  Dashboard,
  Health,
  MarketplaceConnection,
  MarketplaceItemDiagnostics,
  MarketplaceCapability,
  MarketplaceCategory,
  RadarRun,
  RadarSignal,
  CatalogDiscoveryResult,
  TriageResult,
  EnrichmentResult,
  PreferredRadarResult,
  Opportunity, OpportunityOrchestrationResult, OpportunityReviewRequest, OpportunityReviewStatus, OpportunityReviewSummary,
  RadarStatus,
  Candidate,
  Evidence,
  Checklist,
  Assessment,
  CommercialBinding,
} from "../types";
import { apiErrorMessage } from "../lib/apiError";
const BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000/api/v1";
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new Error(apiErrorMessage(body, response.status));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export const api = {
  assess: (id: string) =>
    request<Assessment>("/curator/candidates/" + id + "/assess", {
      method: "POST",
    }),
  assessments: (id: string) =>
    request<Assessment[]>("/curator/candidates/" + id + "/assessments"),
  assessment: (id: string) => request<Assessment>("/curator/assessments/" + id),
  candidates: () => request<Candidate[]>("/curator/candidates"),
  candidate: (id: string) => request<Candidate>("/curator/candidates/" + id),
  createCandidate: (body: Record<string, unknown>) =>
    request<Candidate>("/curator/candidates", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateCandidate: (id: string, body: Record<string, unknown>) =>
    request<Candidate>("/curator/candidates/" + id, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  investigate: (id: string) =>
    request<Candidate>("/curator/candidates/from-radar/" + id, {
      method: "POST",
    }),
  evidence: (id: string) =>
    request<Evidence[]>("/curator/candidates/" + id + "/evidence"),
  commercialBinding: (id: string) =>
    request<CommercialBinding>("/curator/candidates/" + id + "/commercial-binding"),
  bindCommercialOffer: (id: string, body: { source: string; confirmMismatch?: boolean }) =>
    request<CommercialBinding>("/curator/candidates/" + id + "/commercial-binding", {
      method: "POST", body: JSON.stringify(body),
    }),
  removeCommercialBinding: (id: string) =>
    request<void>("/curator/candidates/" + id + "/commercial-binding", { method: "DELETE" }),
  setCommercialAffiliateUrl: (id: string, body: { affiliateUrl: string; confirmReplace?: boolean }) =>
    request<CommercialBinding>("/curator/candidates/" + id + "/commercial-binding/affiliate", {
      method: "PATCH", body: JSON.stringify(body),
    }),
  addEvidence: (id: string, body: Record<string, unknown>) =>
    request<Evidence>("/curator/candidates/" + id + "/evidence", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  checklist: (id: string) =>
    request<Checklist>("/curator/candidates/" + id + "/checklist"),
  archiveCandidate: (id: string) =>
    request<Candidate>("/curator/candidates/" + id + "/archive", {
      method: "POST",
    }),
  reopenCandidate: (id: string) =>
    request<Candidate>("/curator/candidates/" + id + "/reopen", {
      method: "POST",
    }),
  dashboard: () => request<Dashboard>("/dashboard"),
  health: () => request<Health>("/health"),
  settings: () => request<Settings>("/settings"),
  patchSettings: (body: Partial<Settings>) =>
    request<Settings>("/settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  pause: () => request<Settings>("/automation/pause", { method: "POST" }),
  resume: () => request<Settings>("/automation/resume", { method: "POST" }),
  approvals: (status = "") =>
    request<Approval[]>(`/approvals${status ? `?status=${status}` : ""}`),
  decide: (id: string, decision: "approve" | "reject", reason = "") =>
    request<Approval>(`/approvals/${id}/${decision}`, {
      method: "POST",
      body: JSON.stringify({ reason: reason || null }),
    }),
  notifications: () => request<Notification[]>("/notifications"),
  read: (id: string) =>
    request<Notification>(`/notifications/${id}/read`, { method: "POST" }),
  readAll: () =>
    request<{ updated: number }>("/notifications/read-all", { method: "POST" }),
  decisions: () => request<Decision[]>("/decisions"),
  tasks: () => request<AgentTask[]>("/tasks"),
  createTask: (body: { type: string; title: string; isAutomatic: boolean }) =>
    request<AgentTask>("/tasks", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  runTask: (id: string) =>
    request<AgentTask>(`/tasks/${id}/run`, { method: "POST" }),
  cancelTask: (id: string) =>
    request<AgentTask>(`/tasks/${id}/cancel`, { method: "POST" }),
  marketplace: () =>
    request<MarketplaceConnection>("/marketplaces/mercado-livre"),
  marketplaceCapabilities: () =>
    request<MarketplaceCapability[]>(
      "/marketplaces/mercado-livre/capabilities",
    ),
  runMarketplaceDiagnostics: (categoryId: string) =>
    request<MarketplaceConnection>("/marketplaces/mercado-livre/diagnostics", {
      method: "POST",
      body: JSON.stringify({ categoryId }),
    }),
  runMarketplaceItemDiagnostics: (item: string) =>
    request<MarketplaceItemDiagnostics>(
      "/marketplaces/mercado-livre/diagnostics/item",
      { method: "POST", body: JSON.stringify({ item }) },
    ),
  radarStatus: () => request<RadarStatus>("/radar/mercado-livre/status"),
  radarCategories: () =>
    request<MarketplaceCategory[]>("/radar/mercado-livre/categories"),
  syncRadarCategories: () =>
    request<{ fetched: number; inserted: number; updated: number }>(
      "/radar/mercado-livre/categories/sync",
      { method: "POST" },
    ),
  radarRuns: () => request<RadarRun[]>("/radar/mercado-livre/runs"),
  createRadarRun: (categoryId: string | null) =>
    request<RadarRun>("/radar/mercado-livre/runs", {
      method: "POST",
      body: JSON.stringify({ categoryId }),
    }),
  runPreferredRadar: () => request<PreferredRadarResult>("/radar/mercado-livre/runs/preferred", { method:"POST" }),
  runOpportunityOrchestration: () => request<OpportunityOrchestrationResult>("/radar/mercado-livre/opportunities/run-preferred", {method:"POST"}),
  opportunities: (limit=20, reviewStatus:OpportunityReviewStatus|'ALL'='PENDING') => request<Opportunity[]>(`/curator/opportunities?limit=${limit}&reviewStatus=${reviewStatus}`),
  opportunityReviewSummary: () => request<OpportunityReviewSummary>('/curator/opportunities/review-summary'),
  updateOpportunityReview: (id:string, body:OpportunityReviewRequest) => request<{candidateId:string;opportunityReviewStatus:OpportunityReviewStatus;opportunityReviewedAt:string|null;opportunityReviewReason:string|null}>(`/curator/candidates/${id}/opportunity-review`, {method:'PATCH',body:JSON.stringify(body)}),
  directedOpportunitySearch: (query: string, categoryId: string | null) =>
    request<{ runId:string; query:string; policyStatus:string; reasonCode?:string; message?:string; categoryContext:{ domainName?:string|null; predictedCategoryName?:string|null }; productsFoundRaw?:number; productsSelected?:number; candidatesCreated?:number; candidatesReused?:number; topCandidates:Array<{candidateId:string;catalogProductId:string;title:string;relevanceScore?:number;triageScore:number;triageStatus:string;reasons:string[]}> }>("/radar/mercado-livre/directed-search", { method:"POST", body:JSON.stringify({query,categoryId}) }),
  radarSignals: (runId: string) =>
    request<RadarSignal[]>(`/radar/mercado-livre/runs/${runId}/signals`),
  resolveRadarProducts: (runId: string) =>
    request<CatalogDiscoveryResult>(`/radar/mercado-livre/runs/${runId}/resolve-products`, { method: 'POST' }),
  triageRadarCandidates: (runId: string) => request<TriageResult>(`/radar/mercado-livre/runs/${runId}/triage`, { method: 'POST' }),
  enrichRadarCandidates: (runId: string) => request<EnrichmentResult>(`/radar/mercado-livre/runs/${runId}/enrich`, { method: 'POST' }),
  enrichCandidate: (id: string) => request<EnrichmentResult['candidates'][number]>(`/curator/candidates/${id}/enrich`, { method: 'POST' }),
};

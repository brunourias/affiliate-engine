import { useCallback } from "react";
import { Link } from "react-router-dom";
import { campaignsApi } from "../api/campaigns";
import { Badge, Empty, ErrorState, Loading, Section } from "../components/ui";
import { useLoad } from "../hooks";
import { label, statusTone } from "../lib/presentation";

export function CampaignsPage() {
  const load = useCallback(() => campaignsApi.list(), []);
  const { data, error, loading, refresh } = useLoad(load);
  if (loading) return <Loading />;
  if (error || !data)
    return <ErrorState error={error ?? new Error("Sem dados")} retry={refresh} />;
  const count = (status: string) => data.filter((campaign) => campaign.status === status).length;
  return (
    <>
      <header className="page-head">
        <div>
          <span>CAMPAIGN ENGINE</span>
          <h1>Campanhas</h1>
          <p>Famílias de experimentos editoriais com aprovação humana.</p>
        </div>
        <Link className="primary-button" to="/curator">+ Nova campanha</Link>
      </header>
      <div className="metric-grid">
        {[["DRAFT", "Rascunhos"], ["PENDING_APPROVAL", "Aguardando aprovação"], ["APPROVED", "Aprovadas"], ["PAUSED", "Pausadas"]].map(([status, title]) => (
          <div key={status}><b>{count(status)}</b><span>{title}</span></div>
        ))}
      </div>
      <Section title="Campanhas">
        {data.length ? (
          <div className="compact-list">
            {data.map((campaign) => (
              <Link key={campaign.id} to={`/campanhas/${campaign.id}`}>
                <span><b>{campaign.name}</b><small>{label(campaign.editorialVerdictSnapshot)} · Recommendation {campaign.recommendationScoreSnapshot ?? "—"} · Opportunity {campaign.opportunityScoreSnapshot ?? "—"}</small></span>
                <Badge tone={statusTone(campaign.campaignPriority)}>{label(campaign.campaignPriority)}</Badge>
                <strong>{label(campaign.status)}</strong>
              </Link>
            ))}
          </div>
        ) : <Empty>Nenhuma campanha criada.</Empty>}
      </Section>
    </>
  );
}

export { CampaignWorkspace as CampaignPage } from "./CampaignWorkspace";

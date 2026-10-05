import { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import { campaignsApi } from '../api/campaigns';
import { creativesApi } from '../api/creatives';
import { FormatDecision } from '../components/FormatDecision';
import { MediaProduction } from '../components/MediaProduction';
import { StaticProduction } from '../components/StaticProduction';
import { Badge, ErrorState, Loading } from '../components/ui';
import { useLoad } from '../hooks';
import { creativeStatusLabel, label, statusTone } from '../lib/presentation';

export function CreativeMediaPage() {
  const { id = '' } = useParams();
  const load = useCallback(async () => {
    const creative = await creativesApi.get(id);
    if (creative.status !== 'APPROVED') return { creative, campaign: null, requiresVoice: false };
    const [campaign, scenes] = await Promise.all([campaignsApi.get(creative.campaignId), creativesApi.scenes(id)]);
    return { creative, campaign, requiresVoice: scenes.some((scene) => Boolean(scene.narrationText) && scene.speaker !== 'NONE') };
  }, [id]);
  const { data, error, loading, refresh } = useLoad(load);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Erro')} retry={refresh} />;

  const { creative, campaign, requiresVoice } = data;
  if (creative.status !== 'APPROVED') {
    return <main className="media-workspace">
      <Link className="creative-back" to={`/criativos/${id}`}>← Voltar ao criativo</Link>
      <header className="media-workspace-hero"><span className="creative-eyebrow">PRODUÇÃO DE MÍDIA</span><h1>{creative.name}</h1><Badge tone={statusTone(creative.status)}>{creativeStatusLabel(creative.status)}</Badge></header>
      <section className="panel media-blocked-state" role="status"><h2>Este criativo ainda não pode produzir mídia.</h2><p>A produção de vídeo fica disponível depois da aprovação do criativo.</p><Link className="primary-button" to={`/criativos/${id}`}>Voltar ao criativo</Link></section>
    </main>;
  }

  return <main className="media-workspace">
    <Link className="creative-back" to={`/criativos/${id}`}>← Voltar ao criativo</Link>
    <header className="media-workspace-hero">
      <div><span className="creative-eyebrow">PRODUÇÃO DE MÍDIA</span><h1>{creative.name}</h1></div>
      <div className="media-workspace-badges"><Badge tone="success">{creativeStatusLabel(creative.status)}</Badge><Badge>{label(creative.targetChannel)}</Badge><Badge>{label(creative.contentType)}</Badge></div>
      <p>Prepare e renderize mídia em etapas controladas. Preparar uma produção não inicia a renderização.</p>
      {campaign && <small>Campanha: <Link to={`/campanhas/${campaign.id}`}>{campaign.name}</Link></small>}
    </header>

    {campaign && <MediaProduction creativeId={creative.id} candidateId={campaign.candidateId} requiresVoice={requiresVoice} />}

    <section className="panel media-secondary-formats">
      <details>
        <summary>Outros formatos e recomendações</summary>
        <p className="muted">A produção controlada desta página prepara vídeos. Formatos estáticos e recomendações ficam separados.</p>
        <FormatDecision creativeId={creative.id} />
        <StaticProduction creativeId={creative.id} />
      </details>
    </section>
  </main>;
}

import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { campaignsApi } from '../api/campaigns';
import { creativesApi } from '../api/creatives';
import { CreativeApprovalActions } from '../components/CreativeApprovalActions';
import { CreativeSceneEditor } from '../components/CreativeSceneEditor';
import { Badge, Empty, ErrorState, Loading, Section } from '../components/ui';
import { useLoad } from '../hooks';
import { creativeStatusLabel, label, statusTone } from '../lib/presentation';
import type { Creative } from '../types';
import './CreativeWorkspace.css';

type EditorialDraft = { title: string; premise: string; hook: string; body: string; cta: string; duration: string; channel: string };
const emptyDraft: EditorialDraft = { title: '', premise: '', hook: '', body: '', cta: '', duration: '20', channel: 'GENERIC' };
const draftFrom = (creative: Creative): EditorialDraft => ({
  title: creative.title ?? '', premise: creative.contentPremise ?? '', hook: creative.hook ?? '', body: creative.bodyScript ?? '',
  cta: creative.cta ?? '', duration: String(creative.estimatedDurationSeconds ?? 20), channel: creative.targetChannel,
});
const readinessGroups = [
  { title: 'Conteúdo', keys: ['hook', 'bodyScript', 'cta'] },
  { title: 'Estrutura', keys: ['sceneCount', 'disclosure'] },
  { title: 'Conformidade', keys: ['warningCoverage', 'compliance', 'campaignApproved'] },
];
const readinessLabels: Record<string, string> = { hook: 'Hook', bodyScript: 'Roteiro', cta: 'Chamada para ação', sceneCount: 'Cenas', disclosure: 'Aviso de afiliação', warningCoverage: 'Advertências', compliance: 'Alegações', campaignApproved: 'Campanha aprovada' };
const contentTypes = ['GENERIC', 'TIKTOK', 'INSTAGRAM_REELS', 'YOUTUBE_SHORTS', 'FACEBOOK_REELS', 'WHATSAPP', 'WEBSITE'];
const sceneTypes = ['AVATAR', 'PRODUCT', 'TEXT', 'COMPARISON', 'PROS_CONS', 'PRICE', 'WARNING', 'CTA', 'BROLL', 'MIXED'];
const speakers = ['NONE', 'BRUNO', 'CAROL', 'NARRATOR'];
const purposes = ['HOOK', 'BENEFIT', 'LIMITATION', 'CONCLUSION', 'CTA', 'CONTEXT', 'EVIDENCE', 'DISCLOSURE'];

export function CreativeWorkspace() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const load = useCallback(async () => {
    const [creative, scenes, readiness, direction] = await Promise.all([
      creativesApi.get(id), creativesApi.scenes(id), creativesApi.readiness(id), creativesApi.direction(id),
    ]);
    const campaign = await campaignsApi.get(creative.campaignId);
    return { creative, scenes, readiness, direction, campaign };
  }, [id]);
  const { data, error, loading, refresh } = useLoad(load);
  const [draft, setDraft] = useState<EditorialDraft>(emptyDraft);
  const [initializedId, setInitializedId] = useState('');
  const [saveState, setSaveState] = useState('');
  const [saving, setSaving] = useState(false);
  const [templateBusy, setTemplateBusy] = useState(false);
  const [confirmOverwrite, setConfirmOverwrite] = useState(false);
  const [templateError, setTemplateError] = useState('');
  const [actionError, setActionError] = useState('');
  const [duplicating, setDuplicating] = useState(false);
  const [tiktokBusy, setTiktokBusy] = useState(false);
  const [addingScene, setAddingScene] = useState(false);
  const [sceneBusy, setSceneBusy] = useState(false);
  const [sceneError, setSceneError] = useState('');

  useEffect(() => {
    if (data && initializedId !== id) {
      setDraft(draftFrom(data.creative));
      setInitializedId(id);
      setSaveState('');
    }
  }, [data, id, initializedId]);

  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Erro')} retry={refresh} />;

  const { creative, scenes, readiness, direction, campaign } = data;
  const editable = ['DRAFT', 'REJECTED'].includes(creative.status);
  const approved = creative.status === 'APPROVED';
  const readOnlyMessage = creative.status === 'APPROVED'
    ? 'Criativo aprovado — conteúdo bloqueado para edição.'
    : creative.status === 'READY_FOR_REVIEW'
      ? 'Criativo em revisão — aguarde a decisão para editar novamente.'
      : creative.status === 'ARCHIVED'
        ? 'Criativo arquivado — conteúdo somente para consulta.'
        : creative.status === 'REJECTED'
          ? 'Este criativo foi rejeitado e pode ser revisado.' : '';
  const checks = readiness.checks ?? {};
  const totalChecks = Object.keys(checks).length;
  const passedChecks = Object.values(checks).filter(Boolean).length;
  const readyToSubmit = readiness.state === 'READY_FOR_REVIEW';
  const nextAction = creative.status === 'DRAFT'
    ? readyToSubmit ? 'Pronto para revisão' : 'Complete o conteúdo do criativo'
    : creative.status === 'READY_FOR_REVIEW' ? 'Aguardando decisão'
      : creative.status === 'APPROVED' ? 'Criativo aprovado'
        : creative.status === 'REJECTED' ? 'Revisar criativo' : 'Criativo arquivado';
  const notice = (location.state as { notice?: string } | null)?.notice;

  const goToEditorial = () => {
    const section = document.getElementById('creative-editorial');
    if (!section) return;
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    section.focus({ preventScroll: true });
  };

  const setField = (key: keyof EditorialDraft, value: string) => {
    if (!editable) return;
    setDraft((current) => ({ ...current, [key]: value }));
    setSaveState('Alterações não salvas');
  };

  const save = async () => {
    if (!editable || saving) return;
    setSaving(true);
    setSaveState('Salvando…');
    setActionError('');
    try {
      await creativesApi.patch(id, {
        title: draft.title, contentPremise: draft.premise, hook: draft.hook, bodyScript: draft.body,
        cta: draft.cta, estimatedDurationSeconds: Number(draft.duration), targetChannel: draft.channel,
      });
      setSaveState('Salvo');
      refresh();
    } catch (caught) {
      setSaveState('Alterações não salvas');
      setActionError(caught instanceof Error ? caught.message : 'Não foi possível salvar o criativo.');
    } finally {
      setSaving(false);
    }
  };

  const generateTemplate = async (overwrite: boolean) => {
    setTemplateBusy(true);
    setTemplateError('');
    setConfirmOverwrite(false);
    try {
      const generated = await creativesApi.template(id, overwrite);
      setDraft(draftFrom(generated));
      setSaveState('Salvo');
      refresh();
    } catch (caught) {
      setTemplateError(caught instanceof Error ? caught.message : 'Não foi possível gerar a estrutura inicial.');
    } finally {
      setTemplateBusy(false);
    }
  };

  const duplicate = async () => {
    if (duplicating) return;
    setDuplicating(true);
    setActionError('');
    try {
      const copy = await creativesApi.duplicate(id);
      navigate(`/criativos/${copy.id}`, { state: { notice: 'Cópia criada. Você pode editar este Creative.' } });
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Não foi possível criar a cópia editável.');
    } finally {
      setDuplicating(false);
    }
  };

  const createTikTokVariant = async () => {
    if (tiktokBusy) return;
    setTiktokBusy(true);
    setActionError('');
    try {
      const copy = await creativesApi.tiktokVariant(id);
      navigate(`/criativos/${copy.id}`, { state: { notice: 'Versão TikTok-first criada para revisão e edição.' } });
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Não foi possível criar a versão TikTok-first.');
    } finally {
      setTiktokBusy(false);
    }
  };

  const addScene = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editable || sceneBusy) return;
    const form = new FormData(event.currentTarget);
    setSceneBusy(true);
    setSceneError('');
    try {
      await creativesApi.addScene(id, {
        orderIndex: scenes.length, sceneType: form.get('type'), speaker: form.get('speaker'), purpose: form.get('purpose'),
        narrationText: form.get('narration') || null,
      });
      setAddingScene(false);
      refresh();
    } catch (caught) {
      setSceneError(caught instanceof Error ? caught.message : 'Não foi possível adicionar a cena.');
    } finally {
      setSceneBusy(false);
    }
  };

  return <main className="creative-workspace">
    {notice && <p className="creative-notice" role="status">{notice}</p>}

    <header className="creative-hero">
      <Link className="creative-back" to="/criativos">← Criativos</Link>
      <div className="creative-hero-main">
        <div className="creative-hero-title">
          <span className="creative-eyebrow">CRIATIVO</span>
          <h1>{creative.name}</h1>
          <p>Campanha: <Link to={`/campanhas/${campaign.id}`}>{campaign.name}</Link></p>
          <small>{creative.experimentId ? 'Experimento associado' : 'Estratégia base da campanha'}</small>
        </div>
        <div className="creative-badges" aria-label="Estado e formato do criativo">
          <Badge tone={statusTone(creative.status)}>{creativeStatusLabel(creative.status)}</Badge>
          <Badge>{label(creative.targetChannel)}</Badge>
          <Badge>{label(creative.contentType)}</Badge>
        </div>
      </div>
      {readOnlyMessage && <p className={`creative-readonly ${creative.status === 'REJECTED' ? 'is-rejected' : ''}`} role="status">{readOnlyMessage}</p>}
    </header>

    <div className="creative-focus-grid">
      <section className="creative-next-action" aria-labelledby="creative-next-title">
        <div className="creative-panel-heading"><div><span className="creative-eyebrow">PRÓXIMA AÇÃO</span><h2 id="creative-next-title">{nextAction}</h2></div></div>
        <p>{creative.status === 'DRAFT' ? readyToSubmit ? 'O conteúdo atende aos requisitos atuais e pode ser enviado para revisão.' : 'Preencha o conteúdo e resolva os itens pendentes antes do envio.' : creative.status === 'READY_FOR_REVIEW' ? 'O criativo aguarda uma decisão humana.' : creative.status === 'APPROVED' ? 'Conteúdo aprovado. Edição bloqueada; ações seguintes são opcionais.' : creative.status === 'REJECTED' ? 'Atualize o conteúdo e salve as alterações para uma nova revisão.' : 'Este criativo está disponível somente para consulta.'}</p>
        {['DRAFT', 'REJECTED', 'READY_FOR_REVIEW'].includes(creative.status) && <CreativeApprovalActions creativeId={id} status={creative.status} nextAction={readiness.nextAction} showSubmit={readyToSubmit || readiness.nextAction === 'READY_TO_SUBMIT'} onChanged={refresh} />}
        {creative.status === 'DRAFT' && readiness.state === 'NOT_READY' && <button type="button" className="ghost-button creative-next-link" onClick={goToEditorial}>Ir para conteúdo</button>}
        {actionError && <p className="inline-error" role="alert">{actionError}</p>}
      </section>

      <section className="creative-preparation" aria-labelledby="creative-preparation-title">
        <div className="creative-panel-heading"><div><span className="creative-eyebrow">PREPARAÇÃO</span><h2 id="creative-preparation-title">{passedChecks} de {totalChecks} requisitos atendidos</h2></div><Badge tone={readiness.state === 'READY_FOR_REVIEW' || readiness.state === 'APPROVED' ? 'success' : 'warning'}>{creative.status === 'READY_FOR_REVIEW' ? creativeStatusLabel(creative.status) : readiness.state === 'READY_FOR_REVIEW' ? 'Pronto para revisão' : readiness.state === 'APPROVED' ? 'Tudo atendido' : 'Há itens pendentes'}</Badge></div>
        <div className="creative-check-groups">{readinessGroups.map((group) => <div key={group.title}><h3>{group.title}</h3><ul>{group.keys.filter((key) => key in checks).map((key) => <li key={key} className={checks[key] ? 'is-complete' : 'is-pending'}><span aria-hidden="true">{checks[key] ? '✓' : '○'}</span>{readinessLabels[key] ?? label(key)}</li>)}</ul></div>)}</div>
        <details className="creative-disclosure"><summary>Ver detalhes da preparação</summary><ul>{Object.entries(checks).map(([key, passed]) => <li key={key}><span>{readinessLabels[key] ?? label(key)}</span><Badge tone={passed ? 'success' : 'warning'}>{passed ? 'Atendido' : 'Pendente'}</Badge></li>)}</ul><p>Estado geral: {label(readiness.state)} · {readiness.sceneCount} {readiness.sceneCount === 1 ? 'cena' : 'cenas'}.</p></details>
      </section>
    </div>

    <section id="creative-editorial" tabIndex={-1} className="panel creative-editorial-section" aria-labelledby="creative-editorial-heading">
      <header className="panel-head"><h2 id="creative-editorial-heading">Conteúdo editorial</h2>{!editable && <Badge>{creativeStatusLabel(creative.status)}</Badge>}</header>
      <div className="creative-editorial-fields">
        <label className="creative-field-wide">Título<input aria-label="Título" readOnly={!editable} value={draft.title} onChange={(event) => setField('title', event.target.value)} /></label>
        <label className="creative-field-wide">Premissa<textarea aria-label="Premissa" rows={1} readOnly={!editable} value={draft.premise} onChange={(event) => setField('premise', event.target.value)} /></label>
        <label className="creative-field-wide creative-field-emphasis">Hook<textarea aria-label="Hook" rows={2} readOnly={!editable} value={draft.hook} onChange={(event) => setField('hook', event.target.value)} /></label>
        <label className="creative-field-wide creative-field-body">Roteiro<textarea aria-label="Roteiro" rows={4} readOnly={!editable} value={draft.body} onChange={(event) => setField('body', event.target.value)} /></label>
        <label className="creative-field-wide">Chamada para ação<textarea aria-label="Chamada para ação" rows={1} readOnly={!editable} value={draft.cta} onChange={(event) => setField('cta', event.target.value)} /></label>
        <label>Canal<select aria-label="Canal" disabled={!editable} value={draft.channel} onChange={(event) => setField('channel', event.target.value)}>{contentTypes.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>
        <label>Duração<select aria-label="Duração" disabled={!editable} value={draft.duration} onChange={(event) => setField('duration', event.target.value)}>{[15, 20, 30, 45, 60].map((value) => <option key={value} value={value}>{value} segundos</option>)}</select></label>
      </div>
      {editable && <div className="creative-savebar"><div aria-live="polite" role="status">{saveState || 'Sem alterações pendentes'}</div><div className="creative-save-actions">
        <button type="button" className="ghost-button" disabled={templateBusy || saving} onClick={() => scenes.length ? setConfirmOverwrite(true) : void generateTemplate(false)}>{templateBusy ? 'Gerando…' : 'Gerar estrutura inicial'}</button>
        <button type="button" className="primary-button" disabled={saving || templateBusy || !saveState.includes('não salvas')} onClick={save}>{saving ? 'Salvando…' : 'Salvar alterações'}</button>
      </div></div>}
      {confirmOverwrite && <div className="creative-confirm" role="group" aria-label="Confirmar substituição da estrutura"><p>Gerar novamente substituirá o roteiro e as cenas atuais.</p><div><button type="button" className="ghost-button" onClick={() => setConfirmOverwrite(false)}>Cancelar</button><button type="button" className="primary-button" disabled={templateBusy} onClick={() => void generateTemplate(true)}>{templateBusy ? 'Gerando…' : 'Gerar novamente'}</button></div></div>}
      {templateError && <p className="inline-error" role="alert">{templateError}</p>}
    </section>

    <Section title="Direção criativa">
      <div className="creative-direction-facts">{[['Persona', direction.persona], ['Ângulo', direction.creativeAngle], ['Tipo de gancho', direction.hookType], ['Chamada para ação', direction.ctaType]].map(([title, value]) => <div key={title}><small>{title}</small><b>{value ? label(value) : 'Não definido'}</b></div>)}</div>
      <div className="creative-suggestion"><h3>Gancho sugerido</h3><p>{direction.hookText || creative.hook || 'Ainda não há uma sugestão de gancho.'}</p>{direction.angleReason && <small>{direction.angleReason}</small>}</div>
      <div className="creative-quality"><h3>Qualidade da direção</h3><ul>{Object.entries(direction.qualityChecks ?? {}).map(([key, value]) => <li key={key}><Badge tone={value === 'PASS' ? 'success' : value === 'FAIL' ? 'danger' : 'warning'}>{value === 'PASS' ? '✓' : value === 'FAIL' ? '!' : '•'}</Badge><span>{label(key)}</span></li>)}</ul></div>
      <details className="creative-storyboard-details"><summary>Ver sequência visual sugerida ({direction.storyboard?.length ?? 0} cenas)</summary><div className="creative-storyboard">{(direction.storyboard ?? []).map((scene, index) => <article key={scene.sceneId ?? scene.orderIndex}><h3>Cena {index + 1} — {label(scene.purpose)}</h3><p>{scene.scriptSegment || 'Sem roteiro sugerido.'}</p><div className="creative-storyboard-meta"><span><small>Personagem</small>{scene.avatarSpeaker ? label(scene.avatarSpeaker) : 'Sem personagem'}</span><span><small>Duração</small>{scene.recommendedDuration} s</span><span><small>Intenção visual</small>{label(scene.visualIntent)}</span></div>{scene.visualUnits?.length > 0 && <details><summary>Detalhes visuais ({scene.visualUnits.length})</summary>{scene.visualUnits.map((unit) => <p key={unit.visualUnitIndex}>{label(unit.visualIntent)} · {unit.onScreenText || 'Sem texto na tela'} · {unit.estimatedDuration} s</p>)}</details>}<details className="creative-technical"><summary>Detalhes técnicos</summary><small>Segmento de fala: {scene.speechSegmentId}</small>{scene.visualUnits?.map((unit) => <small key={`speech-${unit.visualUnitIndex}`}>Segmento visual {unit.visualUnitIndex + 1}: {unit.speechSegmentId}</small>)}</details></article>)}</div></details>
    </Section>

    <Section title="Cenas do criativo" aside={<span className="creative-scene-count">{scenes.length} {scenes.length === 1 ? 'cena' : 'cenas'}</span>}>
      {editable && !addingScene && <button type="button" className="ghost-button creative-add-scene" onClick={() => { setSceneError(''); setAddingScene(true); }}>Adicionar cena</button>}
      {addingScene && editable && <form className="creative-add-form" onSubmit={addScene}>
        <label>Tipo<select name="type">{sceneTypes.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>
        <label>Personagem<select name="speaker">{speakers.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>
        <label>Propósito<select name="purpose">{purposes.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>
        <label className="creative-field-wide">Narração<textarea name="narration" rows={2} /></label>
        <div className="creative-form-actions"><button type="button" className="ghost-button" disabled={sceneBusy} onClick={() => { setAddingScene(false); setSceneError(''); }}>Cancelar</button><button type="submit" className="primary-button" disabled={sceneBusy}>{sceneBusy ? 'Adicionando…' : 'Adicionar cena'}</button></div>
      </form>}
      {sceneError && <p className="inline-error" role="alert">{sceneError}</p>}
      {scenes.length ? <div className="creative-scene-list">{scenes.map((scene, index) => <article className="creative-scene-card" key={scene.id}><div className="creative-scene-number" aria-hidden="true">{index + 1}</div><CreativeSceneEditor creativeId={id} scene={scene} index={index} count={scenes.length} editable={editable} onRefresh={refresh} /></article>)}</div> : <Empty>Nenhuma cena criada ainda.</Empty>}
    </Section>

    <Section title="Conformidade">
      <div className="creative-compliance-heading"><div><span className="creative-eyebrow">CONFORMIDADE</span><h3>{readiness.compliance.status === 'PASS' ? 'Aprovado' : readiness.compliance.status === 'WARN' ? 'Atenção' : 'Bloqueado'}</h3></div></div>
      {readiness.compliance.reasons.map((reason) => <p className="inline-error" key={reason.code}>{reason.message}</p>)}
      <div className="creative-compliance-grid">
        <div><h3>Aviso de afiliação</h3><p>{creative.disclosureText || 'Não definido'}</p></div>
        <div><h3>Advertências obrigatórias</h3>{readiness.compliance.requiredWarningCoverage.length ? <ul>{readiness.compliance.requiredWarningCoverage.map((warning) => <li key={warning.code}>{warning.message} <Badge tone={warning.status === 'COVERED' ? 'success' : 'warning'}>{label(warning.status)}</Badge></li>)}</ul> : <p>Nenhuma advertência obrigatória.</p>}</div>
        <div><h3>Evitar estas alegações</h3>{creative.forbiddenClaims.length ? <div className="creative-claim-list">{creative.forbiddenClaims.map((claim) => <span key={claim}>{label(claim)}</span>)}</div> : <p>Nenhuma alegação proibida configurada.</p>}</div>
      </div>
    </Section>

    {approved && <Section title="Próximos passos"><div className="creative-distribution creative-next-steps">
      <article><div><h3>Produção de mídia</h3><p>Prepare um preview ou vídeo final. Preparar uma produção não inicia a renderização.</p></div><Link className="primary-button" to={`/criativos/${id}/midia`}>Abrir produção de mídia</Link></article>
      <article><div><h3>Publicação</h3><p>É uma etapa separada e sempre exige confirmação explícita. Nada será publicado automaticamente.</p></div><Link className="ghost-button" to={`/criativos/${id}/publicar/instagram`}>Preparar publicação</Link></article>
    </div></Section>}

    <details className="creative-advanced"><summary>Ações avançadas e rastreabilidade</summary>
      <div className="creative-advanced-content">
        <section><h2>Ações avançadas</h2><p>Opções secundárias; não alteram a aprovação nem publicam automaticamente.</p><div className="creative-advanced-actions">
          {approved && <button type="button" className="ghost-button" disabled={duplicating} onClick={duplicate}>{duplicating ? 'Criando cópia…' : 'Criar cópia editável'}</button>}
          {approved && <button type="button" className="ghost-button" disabled={tiktokBusy} onClick={createTikTokVariant}>{tiktokBusy ? 'Criando versão…' : 'Criar versão TikTok-first'}</button>}
          {editable && <button type="button" className="ghost-button" onClick={async () => { try { const variant = await creativesApi.variant(id); navigate(`/criativos/${variant.id}`); } catch (caught) { setActionError(caught instanceof Error ? caught.message : 'Não foi possível criar a variante.'); } }}>Duplicar como variante</button>}
        </div></section>
        <section><h2>Origem e rastreabilidade</h2><dl>{[['Origem', creative.creationSource ? label(creative.creationSource) : 'Não informada'], ['Aprovação de campanha', creative.sourceCampaignApprovalId], ['Análise de origem', creative.sourceAssessmentId], ['Chave de criação', creative.creationKey]].map(([title, value]) => <div key={title}><dt>{title}</dt><dd>{value || '—'}</dd></div>)}</dl></section>
      </div>
    </details>

  </main>;
}

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { campaignsApi } from '../api/campaigns';
import { campaignHandoffLabel, label, statusTone } from '../lib/presentation';
import type { Assessment, CampaignHandoff, CampaignHandoffCampaignState, CampaignHandoffStatus } from '../types';
import { Badge } from './ui';

const unavailable = (value: number | null | undefined) => value === null || value === undefined ? 'Não disponível' : String(value);

function createErrorMessage(code: string) {
  const messages: Record<string, string> = {
    CAMPAIGN_HANDOFF_REQUIRED: 'A oportunidade precisa ser encaminhada antes de criar a campanha.',
    CAMPAIGN_HANDOFF_STALE: 'A análise comercial mudou. Revise a versão atual antes de criar a campanha.',
    ASSESSMENT_CHANGED: 'A análise comercial mudou. Revise a versão atual antes de criar a campanha.',
    ASSESSMENT_NOT_AVAILABLE: 'A análise comercial ainda não está disponível.',
    CANDIDATE_ARCHIVED: 'Esta oportunidade está arquivada.',
    MULTIPLE_CAMPAIGNS_FOR_ASSESSMENT: 'Existem múltiplas campanhas históricas para esta análise. A vinculação precisa ser revisada antes de continuar.',
  };
  return messages[code] ?? 'Não foi possível criar a campanha. Tente novamente.';
}

export function CampaignHandoffGate({ candidateId, status, onDone, compact = false, showStatus = true }: { candidateId:string; status:CampaignHandoffStatus; onDone:()=>Promise<void>|void; compact?:boolean; showStatus?:boolean }) {
  const [handoff,setHandoff]=useState<CampaignHandoff|null>(null);
  const [assessment,setAssessment]=useState<Assessment|null>(null);
  const [campaignState,setCampaignState]=useState<CampaignHandoffCampaignState|null>(null);
  const [open,setOpen]=useState(false);
  const [busy,setBusy]=useState(false);
  const [creating,setCreating]=useState(false);
  const createLock=useRef(false);
  const [error,setError]=useState('');
  const [message,setMessage]=useState('');

  const loadCampaignState = useCallback(async () => {
    const state=await campaignsApi.campaignFromHandoffState(candidateId);
    setCampaignState(state);
    return state;
  },[candidateId]);

  const load = useCallback(async () => {
    const current=await api.campaignHandoff(candidateId);
    setHandoff(current);
    if(current.status==='APPROVED'&&current.isCurrentAssessment) await loadCampaignState();
    else setCampaignState(null);
    return current;
  },[candidateId,loadCampaignState]);

  useEffect(() => {
    if(status==='STALE'||status==='APPROVED'||status==='REJECTED') void load().catch(()=>undefined);
  },[load,status]);

  const openReview = async () => {
    setError('');setMessage('');
    try {
      const current=await load();
      setAssessment(current.currentAssessmentId?await api.assessment(current.currentAssessmentId):null);
      setOpen(true);
    } catch { setError('Não foi possível carregar a decisão atual.'); }
  };

  const decide = async (next:'APPROVED'|'REJECTED'|'NOT_DECIDED', reason:string|null = null) => {
    if(busy)return;
    setBusy(true);setError('');
    try {
      const current=handoff??await api.campaignHandoff(candidateId);
      const body=next==='NOT_DECIDED'?{status:next}:{status:next,assessmentId:current.currentAssessmentId,reason};
      const updated=await api.updateCampaignHandoff(candidateId,body);
      setHandoff(updated);setOpen(false);
      if(next==='APPROVED'&&updated.isCurrentAssessment) await loadCampaignState();
      else if(next!=='APPROVED') setCampaignState(null);
      setMessage(next==='REJECTED'?'Oportunidade marcada como não encaminhada.':next==='NOT_DECIDED'?'Decisão reaberta.':'');
      await onDone();
    } catch (failure) {
      const code=failure instanceof Error?failure.message:'';
      if(code==='ASSESSMENT_CHANGED') { setError('A análise comercial mudou enquanto você revisava esta oportunidade. Atualizamos os dados. Revise a versão mais recente antes de decidir.');await load();await onDone(); }
      else setError('Não foi possível registrar a decisão. Tente novamente.');
    } finally { setBusy(false); }
  };

  const createCampaign = async () => {
    if(createLock.current||creating)return;
    createLock.current=true;setCreating(true);setError('');setMessage('');
    try {
      const result=await campaignsApi.createFromHandoff(candidateId);
      const campaign=result.campaign;
      setCampaignState({state:'CAMPAIGN_EXISTS',campaignId:campaign.id,campaignName:campaign.name,campaignStatus:campaign.status,assessmentId:campaign.assessmentId,assessmentVersion:campaignState?.assessmentVersion??handoff?.currentAssessmentVersion??null,reasonCode:null});
      setMessage(result.created?'Campanha criada como rascunho.':'A campanha desta análise já existe.');
      await onDone();
    } catch (failure) {
      const code=failure instanceof Error?failure.message:'';
      setError(createErrorMessage(code));
      if(['CAMPAIGN_HANDOFF_REQUIRED','CAMPAIGN_HANDOFF_STALE','ASSESSMENT_CHANGED','ASSESSMENT_NOT_AVAILABLE','CANDIDATE_ARCHIVED','MULTIPLE_CAMPAIGNS_FOR_ASSESSMENT'].includes(code)) await load().catch(()=>undefined);
    } finally { createLock.current=false;setCreating(false); }
  };

  const effective=handoff?.status??status;
  const effectiveStatus=effective==='APPROVED'&&handoff&&!handoff.isCurrentAssessment?'STALE':effective;
  if(effectiveStatus==='STALE') return <div className="campaign-handoff">{showStatus&&<Badge tone="warning">Revisão necessária</Badge>}<p>A análise comercial mudou desde a última decisão. Revise a análise atual antes de encaminhar esta oportunidade.</p>{!open&&<button type="button" className="primary-button" onClick={openReview}>Revisar nova análise</button>}{error&&<p className="inline-error" role="alert">{error}</p>}{open&&<HandoffDialog handoff={handoff} assessment={assessment} busy={busy} decide={decide} cancel={()=>setOpen(false)}/>}</div>;

  if(effectiveStatus==='APPROVED') return <div className="campaign-handoff">
    {showStatus&&<Badge tone={statusTone('APPROVED')}>{campaignHandoffLabel('APPROVED')}</Badge>}
    {showStatus&&handoff?.reason&&<small>Motivo: {handoff.reason}</small>}
    {campaignState?.state==='READY_TO_CREATE'&&<div className="campaign-creation-result">{!compact&&<p>Esta oportunidade está autorizada a gerar uma campanha em rascunho. Isso não aprova nem publica a campanha.</p>}<button type="button" className="primary-button" disabled={creating} onClick={createCampaign}>{creating?'Criando…':'Criar campanha'}</button></div>}
    {campaignState?.state==='CAMPAIGN_EXISTS'&&<div className="campaign-creation-result">{!compact&&<><b>Campanha criada</b><p>{campaignState.campaignName}</p><Badge tone={statusTone(campaignState.campaignStatus??'DRAFT')}>{label(campaignState.campaignStatus)}</Badge></>}<Link className="primary-button" to={`/campanhas/${campaignState.campaignId}`}>Abrir campanha</Link></div>}
    {campaignState?.state==='MULTIPLE_CAMPAIGNS'&&<p className="inline-error">Existem múltiplas campanhas históricas para esta análise. A vinculação precisa ser revisada antes de continuar.</p>}
    <button type="button" className="ghost-button" onClick={()=>decide('NOT_DECIDED')}>Reabrir decisão</button>
    {message&&<p role="status">{message}</p>}{error&&<p className="inline-error" role="alert">{error}</p>}
  </div>;

  if(effectiveStatus==='REJECTED') return <div className="campaign-handoff">{showStatus&&<Badge tone={statusTone('REJECTED')}>{campaignHandoffLabel('REJECTED')}</Badge>}{showStatus&&handoff?.reason&&<small>Motivo: {handoff.reason}</small>}<button type="button" className="ghost-button" onClick={()=>decide('NOT_DECIDED')}>Reabrir decisão</button>{message&&<p role="status">{message}</p>}{error&&<p className="inline-error" role="alert">{error}</p>}</div>;

  return <div className="campaign-handoff">{showStatus&&<Badge tone="neutral">Aguardando decisão</Badge>}{!compact&&<p>A análise comercial está disponível e aguarda sua decisão.</p>}{!open&&<button type="button" className="primary-button" onClick={openReview}>Revisar e encaminhar</button>}{message&&<p role="status">{message}</p>}{error&&<p className="inline-error" role="alert">{error}</p>}{open&&<HandoffDialog handoff={handoff} assessment={assessment} busy={busy} decide={decide} cancel={()=>setOpen(false)}/>}</div>;
}

function HandoffDialog({handoff,assessment,busy,decide,cancel}:{handoff:CampaignHandoff|null;assessment:Assessment|null;busy:boolean;decide:(status:'APPROVED'|'REJECTED', reason:string|null)=>void;cancel:()=>void}) {
  const submit=(event:FormEvent<HTMLFormElement>)=>{
    event.preventDefault();
    const submitter=(event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement|null;
    const status=submitter?.value;
    if(status!=='APPROVED'&&status!=='REJECTED')return;
    const formData=new FormData(event.currentTarget);
    const reason=String(formData.get('reason')??'').trim()||null;
    decide(status,reason);
  };
  return <form className="opportunity-confirm campaign-handoff-dialog" role="dialog" aria-label="Decidir encaminhamento para campanha" onSubmit={submit}><h3>Decidir encaminhamento</h3><p>Análise v{handoff?.currentAssessmentVersion??'—'} · Esta ação autoriza a criação futura de uma campanha baseada no Assessment atual, mas não cria nem publica uma campanha agora.</p><div className="connection-grid"><div><small>Qualidade das evidências</small><b>{assessment?label(assessment.trustGate):'Não disponível'}</b></div><div><small>Recomendação</small><b>{unavailable(assessment?.recommendationScore)}</b></div><div><small>Oportunidade</small><b>{unavailable(assessment?.opportunityScore)}</b></div><div><small>Preço</small><b>{assessment?label(assessment.priceVerdict):'Não disponível'}</b></div><div><small>Veredito editorial</small><b>{assessment?label(assessment.editorialVerdict):'Não disponível'}</b></div></div><label>Motivo da decisão (opcional)<textarea name="reason" placeholder="Motivo da decisão (opcional)" /></label><div className="diagnostic-controls"><button type="button" className="ghost-button" disabled={busy} onClick={cancel}>Cancelar</button><button type="submit" name="decision" value="REJECTED" disabled={busy}>Não encaminhar</button><button type="submit" name="decision" value="APPROVED" className="primary-button" disabled={busy||!handoff?.currentAssessmentId}>{busy?'Salvando…':'Encaminhar para campanha'}</button></div></form>;
}

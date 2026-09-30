import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api } from '../api/client';
import { campaignHandoffLabel, label, statusTone } from '../lib/presentation';
import type { Assessment, CampaignHandoff, CampaignHandoffStatus } from '../types';
import { Badge } from './ui';

const unavailable = (value: number | null | undefined) => value === null || value === undefined ? 'Não disponível' : String(value);

export function CampaignHandoffGate({ candidateId, status, onDone, compact = false, showStatus = true }: { candidateId:string; status:CampaignHandoffStatus; onDone:()=>Promise<void>|void; compact?:boolean; showStatus?:boolean }) {
  const [handoff,setHandoff]=useState<CampaignHandoff|null>(null); const [assessment,setAssessment]=useState<Assessment|null>(null);
  const [open,setOpen]=useState(false); const [busy,setBusy]=useState(false); const [error,setError]=useState(''); const [message,setMessage]=useState('');
  const load = useCallback(async () => { const current=await api.campaignHandoff(candidateId); setHandoff(current); return current; }, [candidateId]);
  useEffect(() => { if (status === 'STALE' || status === 'APPROVED' || status === 'REJECTED') void load().catch(() => undefined); }, [load, status]);
  const openReview = async () => { setError(''); setMessage(''); try { const current=await load(); setAssessment(current.currentAssessmentId?await api.assessment(current.currentAssessmentId):null); setOpen(true); } catch { setError('Não foi possível carregar a decisão atual.'); } };
  const decide = async (next:'APPROVED'|'REJECTED'|'NOT_DECIDED', reason:string|null = null) => {
    if (busy) return; setBusy(true); setError('');
    try {
      const current=handoff ?? await load();
      const body = next==='NOT_DECIDED' ? {status:next} : {status:next,assessmentId:current.currentAssessmentId,reason};
      const updated=await api.updateCampaignHandoff(candidateId,body); setHandoff(updated); setOpen(false);
      setMessage(next==='REJECTED'?'Oportunidade marcada como não encaminhada.':next==='NOT_DECIDED'?'Decisão reaberta.':''); await onDone();
    } catch (failure) {
      const code=failure instanceof Error ? failure.message : '';
      if (code==='ASSESSMENT_CHANGED') { setError('A análise comercial mudou enquanto você revisava esta oportunidade. Atualizamos os dados. Revise a versão mais recente antes de decidir.'); await load(); await onDone(); }
      else setError('Não foi possível registrar a decisão. Tente novamente.');
    } finally { setBusy(false); }
  };
  const effective=handoff?.status ?? status;
  if (status==='STALE' || effective==='STALE') return <div className="campaign-handoff">{showStatus&&<Badge tone="warning">Revisão necessária</Badge>}<p>A análise comercial mudou desde a última decisão. Revise a análise atual antes de encaminhar esta oportunidade.</p>{!open&&<button type="button" className="primary-button" onClick={openReview}>Revisar nova análise</button>}{error&&<p className="inline-error" role="alert">{error}</p>}{open&&<HandoffDialog handoff={handoff} assessment={assessment} busy={busy} decide={decide} cancel={()=>setOpen(false)}/>}</div>;
  if (effective==='APPROVED' || effective==='REJECTED') return <div className="campaign-handoff">{showStatus&&<Badge tone={statusTone(effective)}>{campaignHandoffLabel(effective)}</Badge>}{effective==='APPROVED'&&<p>Autorizada para a próxima etapa. Nenhuma campanha foi criada automaticamente.</p>}{showStatus&&handoff?.reason&&<small>Motivo: {handoff.reason}</small>}<button type="button" className="ghost-button" onClick={()=>decide('NOT_DECIDED')}>Reabrir decisão</button>{message&&<p role="status">{message}</p>}{error&&<p className="inline-error" role="alert">{error}</p>}</div>;
  return <div className="campaign-handoff">{showStatus&&<Badge tone="neutral">Aguardando decisão</Badge>}{!compact&&<p>A análise comercial está disponível e aguarda sua decisão.</p>}{!open&&<button type="button" className="primary-button" onClick={openReview}>Revisar e encaminhar</button>}{message&&<p role="status">{message}</p>}{error&&<p className="inline-error" role="alert">{error}</p>}{open&&<HandoffDialog handoff={handoff} assessment={assessment} busy={busy} decide={decide} cancel={()=>setOpen(false)}/>}</div>;
}

function HandoffDialog({handoff,assessment,busy,decide,cancel}:{handoff:CampaignHandoff|null;assessment:Assessment|null;busy:boolean;decide:(status:'APPROVED'|'REJECTED', reason:string|null)=>void;cancel:()=>void}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const status = submitter?.value;
    if (status !== 'APPROVED' && status !== 'REJECTED') return;
    const formData = new FormData(event.currentTarget);
    const reason = String(formData.get('reason') ?? '').trim() || null;
    decide(status, reason);
  };
  return <form className="opportunity-confirm campaign-handoff-dialog" role="dialog" aria-label="Decidir encaminhamento para campanha" onSubmit={submit}><h3>Decidir encaminhamento</h3><p>Análise v{handoff?.currentAssessmentVersion ?? '—'} · Esta ação autoriza a criação futura de uma campanha baseada no Assessment atual, mas não cria nem publica uma campanha agora.</p><div className="connection-grid"><div><small>Qualidade das evidências</small><b>{assessment?label(assessment.trustGate):'Não disponível'}</b></div><div><small>Recomendação</small><b>{unavailable(assessment?.recommendationScore)}</b></div><div><small>Oportunidade</small><b>{unavailable(assessment?.opportunityScore)}</b></div><div><small>Preço</small><b>{assessment?label(assessment.priceVerdict):'Não disponível'}</b></div><div><small>Veredito editorial</small><b>{assessment?label(assessment.editorialVerdict):'Não disponível'}</b></div></div><label>Motivo da decisão (opcional)<textarea name="reason" placeholder="Motivo da decisão (opcional)" /></label><div className="diagnostic-controls"><button type="button" className="ghost-button" disabled={busy} onClick={cancel}>Cancelar</button><button type="submit" name="decision" value="REJECTED" disabled={busy}>Não encaminhar</button><button type="submit" name="decision" value="APPROVED" className="primary-button" disabled={busy||!handoff?.currentAssessmentId}>{busy?'Salvando…':'Encaminhar para campanha'}</button></div></form>;
}

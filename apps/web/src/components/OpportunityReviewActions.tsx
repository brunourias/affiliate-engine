import { useState } from 'react';
import { api } from '../api/client';
import { label } from '../lib/presentation';
import type { OpportunityReviewStatus } from '../types';

const actions: Record<OpportunityReviewStatus, Array<[OpportunityReviewStatus, string]>> = {
  PENDING: [['INVESTIGATE','Investigar'],['COMMERCIAL_REVIEW','Seguir para análise comercial'],['DISMISSED','Descartar']],
  INVESTIGATE: [['COMMERCIAL_REVIEW','Seguir para análise comercial'],['DISMISSED','Descartar'],['PENDING','Reabrir como pendente']],
  COMMERCIAL_REVIEW: [['PENDING','Reabrir como pendente'],['INVESTIGATE','Mover para investigando'],['DISMISSED','Descartar']],
  DISMISSED: [['PENDING','Reabrir como pendente']],
};

function message(status: OpportunityReviewStatus) {
  if (status === 'DISMISSED') return 'Descartar esta oportunidade da fila de pendentes? O candidato continuará salvo na Curadoria e poderá ser reaberto depois.';
  if (status === 'COMMERCIAL_REVIEW') return 'Essa ação apenas registra sua decisão. Nenhuma oferta, campanha ou publicação será criada automaticamente.';
  return `Alterar a decisão da oportunidade para ${label(status)}?`;
}

export function OpportunityReviewActions({candidateId,status,onUpdated}:{candidateId:string;status:OpportunityReviewStatus|undefined;onUpdated:()=>Promise<void>|void}) {
  const [target,setTarget]=useState<OpportunityReviewStatus|null>(null); const [reason,setReason]=useState(''); const [busy,setBusy]=useState(false); const [error,setError]=useState('');
  const currentStatus = status ?? 'PENDING';
  const save=async()=>{if(!target||busy)return;setBusy(true);setError('');try{await api.updateOpportunityReview(candidateId,{status:target,reason:reason||null});setTarget(null);setReason('');await onUpdated()}catch(e){setError(e instanceof Error?e.message:'Não foi possível atualizar a decisão.')}finally{setBusy(false)}};
  return <div className="diagnostic-controls opportunity-actions">{actions[currentStatus].map(([next,text])=><button key={next} type="button" className="ghost-button" disabled={busy} onClick={()=>{setTarget(next);setError('')}}>{text}</button>)}{target&&<div className="opportunity-confirm" role="dialog"><p>{message(target)}</p><label>Motivo (opcional)<textarea value={reason} maxLength={1000} placeholder="Ex.: comparar ofertas e avaliações" onChange={event=>setReason(event.target.value)} /></label>{error&&<p className="inline-error" role="alert">{error}</p>}<button type="button" className="ghost-button" disabled={busy} onClick={()=>setTarget(null)}>Cancelar</button><button type="button" className="primary-button" disabled={busy} onClick={save}>{busy?'Salvando…':'Confirmar'}</button></div>}</div>;
}

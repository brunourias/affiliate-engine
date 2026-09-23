import{useEffect,useState}from'react';
import{creativesApi}from'../api/creatives';
import type{Approval}from'../types';

export function CreativeApprovalActions({creativeId,status,onChanged}:{creativeId:string;status:string;onChanged:()=>Promise<unknown>|unknown}){
  const[approval,setApproval]=useState<Approval|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState('');
  useEffect(()=>{let active=true;if(status==='READY_FOR_REVIEW')creativesApi.pendingApproval(creativeId).then(item=>{if(active)setApproval(item)}).catch(e=>{if(active)setError(e instanceof Error?e.message:'Não foi possível carregar a aprovação.')});else setApproval(null);return()=>{active=false}},[creativeId,status]);
  const submit=async()=>{if(busy)return;setBusy(true);setError('');try{const item=await creativesApi.submit(creativeId);setApproval(item);setMessage('Creative enviado para revisão.');await onChanged()}catch(e){setError(e instanceof Error?e.message:'Não foi possível enviar o Creative para revisão.')}finally{setBusy(false)}};
  const decide=async(decision:'approve'|'reject')=>{if(busy||!approval)return;setBusy(true);setError('');try{await creativesApi.decide(approval.id,decision);setMessage(decision==='approve'?'Creative aprovado.':'Creative rejeitado.');await onChanged()}catch(e){setError(e instanceof Error?e.message:'Não foi possível registrar a decisão.')}finally{setBusy(false)}};
  return <div className="creative-approval-actions">{status==='DRAFT'&&<button type="button" className="primary-button" disabled={busy} onClick={submit}>{busy?'Enviando…':'Enviar para revisão'}</button>}{status==='READY_FOR_REVIEW'&&<><button type="button" className="primary-button" disabled={busy||!approval} onClick={()=>decide('approve')}>Aprovar</button><button type="button" className="ghost-button" disabled={busy||!approval} onClick={()=>decide('reject')}>Rejeitar</button></>}{message&&<span role="status">{message}</span>}{error&&<span role="alert" className="inline-error">{error}</span>}</div>;
}

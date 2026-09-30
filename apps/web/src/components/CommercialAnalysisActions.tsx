import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { commercialFeedback } from '../lib/commercialAnalysis';
import type { CommercialAnalysisResult, CommercialAnalysisStatus } from '../types';

export function CommercialAnalysisActions({candidateId,status,onDone}:{candidateId:string;status:CommercialAnalysisStatus;onDone:(result:CommercialAnalysisResult)=>Promise<void>|void}) {
 const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');const [error,setError]=useState('');
 const run=async()=>{if(busy)return;setBusy(true);setError('');try{const result=await api.runCommercialAnalysis(candidateId);setMessage(commercialFeedback(result.commercialAnalysisStatus));await onDone(result)}catch(e){setError(e instanceof Error?e.message:'Não foi possível concluir a análise.')}finally{setBusy(false)}};
 const binding=status==='WAITING_FOR_OFFER';const available=status==='ASSESSMENT_AVAILABLE';
 return <div className="diagnostic-controls commercial-actions">{binding&&<Link className="primary-button" to={`/curator/${candidateId}`}>Vincular oferta</Link>}<button type="button" className={binding?'ghost-button':status==='NOT_STARTED'||status==='FAILED'?'primary-button':'ghost-button'} disabled={busy} onClick={run}>{busy?'Analisando…':status==='NOT_STARTED'?'Executar análise':status==='FAILED'?'Tentar novamente':'Executar novamente'}</button>{available&&<Link to={`/curator/${candidateId}`}>Ver análise</Link>}{message&&<p className="timestamp">{message}</p>}{error&&<p className="inline-error" role="alert">{error}</p>}</div>;
}

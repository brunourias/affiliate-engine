import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { creativesApi } from '../api/creatives';
import type { Approval } from '../types';

export function CreativeApprovalActions({ creativeId, status, nextAction, onChanged, showSubmit = true }: {
  creativeId: string;
  status: string;
  nextAction?: string;
  onChanged: () => Promise<unknown> | unknown;
  showSubmit?: boolean;
}) {
  const [approval, setApproval] = useState<Approval | null>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const needsApprovalLookup = status === 'READY_FOR_REVIEW';

  const refreshApproval = async (preserveExisting = false) => {
    setError('');
    try {
      const item = await creativesApi.pendingApproval(creativeId);
      if (item || !preserveExisting) setApproval(item);
      return item;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Não foi possível localizar a aprovação pendente.');
      return null;
    }
  };

  useEffect(() => {
    let active = true;
    if (needsApprovalLookup) {
      creativesApi.pendingApproval(creativeId).then(item => {
        if (active && item) setApproval(item);
      }).catch(caught => {
        if (active) setError(caught instanceof Error ? caught.message : 'Não foi possível localizar a aprovação pendente.');
      });
    } else {
      setApproval(null);
    }
    return () => { active = false; };
  }, [creativeId, needsApprovalLookup]);

  const submit = async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true); setError(''); setMessage('');
    try {
      const submitted = await creativesApi.submit(creativeId);
      setApproval(submitted);
      setMessage('Criativo enviado para revisão.');
      await onChanged();
      // The refreshed status is READY_FOR_REVIEW; verify the persisted pending Approval before linking.
      const pending = await refreshApproval(true);
      if (!pending) setApproval(submitted);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Não foi possível enviar o criativo para revisão.');
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const canSubmit = ['DRAFT', 'REJECTED'].includes(status) && showSubmit && (nextAction === 'READY_TO_SUBMIT' || nextAction == null);
  return <div className="creative-approval-actions">
    {canSubmit && <button type="button" className="primary-button" disabled={busy} onClick={() => void submit()}>{busy ? 'Enviando…' : status === 'REJECTED' ? 'Reenviar para revisão' : 'Enviar para revisão'}</button>}
    {status === 'READY_FOR_REVIEW' && <>
      <p role="status">Aguardando decisão humana.</p>
      {approval ? <Link className="primary-button small" to={`/aprovacoes/${approval.id}`}>Revisar aprovação</Link> : <div className="creative-approval-missing" role="alert"><p>O criativo está em revisão, mas não foi localizada uma aprovação pendente. Atualize para conferir o estado.</p><button type="button" className="ghost-button small" disabled={busy} onClick={() => void refreshApproval()}>Atualizar</button></div>}
    </>}
    {message && <span role="status">{message}</span>}
    {error && <span role="alert" className="inline-error">{error}</span>}
  </div>;
}

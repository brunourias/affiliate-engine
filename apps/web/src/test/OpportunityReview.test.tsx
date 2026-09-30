import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OpportunityReviewActions } from '../components/OpportunityReviewActions';

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('OpportunityReviewActions', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('confirma investigar com motivo e recarrega após PATCH', async () => {
    const reload = vi.fn();
    const fetchMock = vi.fn(() => response({ candidateId: 'c1', opportunityReviewStatus: 'INVESTIGATE', opportunityReviewedAt: '2026-09-29T21:00:00Z', opportunityReviewReason: 'comparar ofertas' }));
    vi.stubGlobal('fetch', fetchMock);
    render(<OpportunityReviewActions candidateId="c1" status="PENDING" onUpdated={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Investigar' }));
    fireEvent.change(screen.getByPlaceholderText('Ex.: comparar ofertas e avaliações'), { target: { value: 'comparar ofertas' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/v1/curator/candidates/c1/opportunity-review'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ status: 'INVESTIGATE', reason: 'comparar ofertas' }) })));
    await waitFor(() => expect(reload).toHaveBeenCalledOnce());
    expect((fetchMock.mock.calls as unknown as Array<[string]>).some(([url]) => url.includes('/enrich') || url.includes('commercial-binding') || url.includes('/campaign'))).toBe(false);
  });

  it('bloqueia segunda confirmação enquanto salva e mantém erro visível', async () => {
    let reject!: (reason?: unknown) => void;
    const fetchMock = vi.fn(() => new Promise<Response>((_, failure) => { reject = failure; }));
    vi.stubGlobal('fetch', fetchMock);
    render(<OpportunityReviewActions candidateId="c1" status="DISMISSED" onUpdated={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Reabrir como pendente' }));
    const confirm = screen.getByRole('button', { name: 'Confirmar' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    reject(new Error('Falha controlada'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Falha controlada');
  });
});

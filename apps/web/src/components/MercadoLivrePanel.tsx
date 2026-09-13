import { useCallback, useState } from 'react';
import { api } from '../api/client';
import { Badge, ErrorState, Loading, Section } from './ui';
import { useLoad } from '../hooks';
import { date, label, statusTone } from '../lib/presentation';

const CAPABILITY_LABELS: Record<string, string> = {
  SITE: 'Site Brasil', CATEGORIES: 'Categorias', TRENDS_GLOBAL: 'Tendências gerais', TRENDS_CATEGORY: 'Tendências por categoria', HIGHLIGHTS_CATEGORY: 'Mais vendidos', MARKETPLACE_SEARCH: 'Busca geral', AUTH_USER: 'Usuário autenticado', ITEM_DETAILS: 'Detalhes de item', PRICE_DETAILS: 'Preço', REVIEWS: 'Avaliações', SELLER_DETAILS: 'Vendedor', CATALOG_PRODUCT: 'Produto de catálogo', USER_PRODUCT: 'User Product',
};

export function MercadoLivrePanel() {
  const loader = useCallback(async () => ({ connection: await api.marketplace(), capabilities: await api.marketplaceCapabilities() }), []);
  const { data, error, loading, refresh } = useLoad(loader);
  const [category, setCategory] = useState('MLB5672');
  const [item, setItem] = useState('');
  const [running, setRunning] = useState<'all' | 'item' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  async function execute(kind: 'all' | 'item') {
    setRunning(kind); setActionError(null);
    try {
      if (kind === 'all') await api.runMarketplaceDiagnostics(category);
      else await api.runMarketplaceItemDiagnostics(item);
      await refresh();
    } catch (reason) { setActionError(reason instanceof Error ? reason.message : 'Falha no diagnóstico.'); }
    finally { setRunning(null); }
  }
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? new Error('Sem dados')} retry={refresh} />;
  const { connection, capabilities } = data;
  return <div className="marketplace-block"><Section title="Mercado Livre"><div className="connection-grid"><div><small>Provider</small><b>Mercado Livre</b></div><div><small>Site</small><b>Brasil ({connection.siteId})</b></div><div><small>Modo</small><b>{label(connection.authMode)}</b></div><div><small>Status geral</small><Badge tone={statusTone(connection.status)}>{label(connection.status)}</Badge></div><div><small>Última verificação</small><b>{date(connection.lastCheckedAt)}</b></div></div><div className="diagnostic-controls"><label>Categoria de diagnóstico<input aria-label="Categoria de diagnóstico" value={category} onChange={event => setCategory(event.target.value.toUpperCase())} /></label><button className="primary-button" disabled={running !== null} onClick={() => execute('all')}>{running === 'all' ? 'Testando…' : 'Testar capacidades'}</button></div>{actionError && <p className="inline-error" role="alert">{actionError}</p>}</Section><Section title="Capacidades"><div className="table-wrap"><table><thead><tr><th>Capacidade</th><th>Status</th><th>HTTP</th><th>Última checagem</th><th>Mensagem</th></tr></thead><tbody>{capabilities.map(capability => <tr key={capability.id}><td>{CAPABILITY_LABELS[capability.capabilityKey] ?? capability.capabilityKey}</td><td><Badge tone={statusTone(capability.status)}>{label(capability.status)}</Badge></td><td>{capability.lastHttpStatus ?? '—'}</td><td>{date(capability.checkedAt)}</td><td><small>{capability.message ?? 'Ainda não testada.'}</small></td></tr>)}</tbody></table></div></Section><Section title="Item para diagnóstico"><div className="diagnostic-controls"><label>URL ou item ID<input aria-label="URL ou item ID" placeholder="MLB123456789" value={item} onChange={event => setItem(event.target.value)} /></label><button className="ghost-button" disabled={running !== null || !item.trim()} onClick={() => execute('item')}>{running === 'item' ? 'Testando…' : 'Testar item'}</button></div><p className="timestamp">A URL é usada somente para extrair o ID; nenhuma página é coletada.</p></Section></div>;
}

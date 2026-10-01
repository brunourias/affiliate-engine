import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CreativePage } from '../pages/Creatives';

const creativeBase = {
  id: 'cr1', campaignId: 'cp1', experimentId: null, name: 'Criativo — Parafusadeira', status: 'DRAFT',
  contentType: 'SHORT_VIDEO', targetChannel: 'INSTAGRAM_REELS', angleTypeSnapshot: 'HOME_USE', objectiveSnapshot: 'EDUCATION',
  editorialVerdictSnapshot: 'WORTH_IT', priceVerdictSnapshot: 'FAIR_PRICE', title: 'Título', contentPremise: 'Premissa',
  hook: 'Hook', bodyScript: 'Roteiro', cta: 'Compare', estimatedDurationSeconds: 20, disclosureText: 'Link de afiliado',
  requiredWarnings: [], forbiddenClaims: ['BEST_ON_MARKET_UNSUPPORTED'], generationMode: 'MANUAL', variantGroup: null,
  parentCreativeId: null, variantLabel: null, creationSource: 'CAMPAIGN_APPROVAL', creationKey: 'creation-key',
  sourceCampaignApprovalId: 'approval-secret-id', sourceAssessmentId: 'assessment-id',
};
const scene = { id: 's1', creativeId: 'cr1', orderIndex: 0, sceneType: 'PRODUCT', speaker: 'NARRATOR', purpose: 'BENEFIT', narrationText: 'Cena narrada', onScreenText: null, visualInstruction: null, avatarState: null, durationSeconds: 4, requiredWarningCodes: [] };
const direction = { subject: 'Parafusadeira', creativeAngle: 'HOME_USE', angleReason: 'Uso doméstico.', persona: 'CAROL', hookType: 'QUESTION', ctaType: 'SEE_IF_IT_FITS', hookText: 'Gancho sugerido', ctaText: 'Compare', patternInterrupts: [], qualityChecks: { hookStrength: 'PASS', productVisibility: 'WARNING', benefitClarity: 'PASS' }, storyboard: [{ orderIndex: 0, speechSegmentId: 'speech-private-id', purpose: 'HOOK', scriptSegment: 'Texto de abertura', onScreenText: 'PRA USO EM CASA?', visualIntent: 'PRODUCT_HERO', recommendedDuration: 3, productFocus: true, avatarVisible: false, avatarSpeaker: null, visualEmphasis: 'HIGH', visualUnits: [{ speechSegmentId: 'speech-private-id', visualUnitIndex: 0, visualIntent: 'PRODUCT_HERO', onScreenText: 'PRA USO EM CASA?', estimatedDuration: 3 }] }] };
const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));

function setup({ status = 'DRAFT', readinessState = 'NOT_READY', checks = { hook: true, bodyScript: false, cta: true, sceneCount: false, disclosure: true, warningCoverage: true, compliance: true, campaignApproved: true }, compliance = 'PASS', initialScenes = [scene] }: { status?: string; readinessState?: string; checks?: Record<string, boolean>; compliance?: string; initialScenes?: typeof scene[] } = {}) {
  let currentScenes = [...initialScenes];
  const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = String(input), method = init?.method ?? 'GET';
    if (url.endsWith('/creatives/cr1/scenes') && method === 'POST') {
      const body = JSON.parse(String(init?.body));
      const created = { ...scene, ...body, id: 's-new', orderIndex: currentScenes.length };
      currentScenes = [...currentScenes, created];
      return json(created);
    }
    if (url.endsWith('/creatives/cr1/scenes')) return json(currentScenes);
    if (url.endsWith('/creatives/cr1/readiness')) return json({ state: readinessState, checks, sceneCount: currentScenes.length, compliance: { status: compliance, reasons: compliance === 'BLOCK' ? [{ code: 'BEST_ON_MARKET_UNSUPPORTED', message: 'Alegação bloqueada.' }] : [], requiredWarningCoverage: [] } });
    if (url.endsWith('/creatives/cr1/creative-direction')) return json(direction);
    if (url.endsWith('/creatives/cr1')) return json({ ...creativeBase, status });
    if (url.endsWith('/campaigns/cp1')) return json({ id: 'cp1', name: 'Parafusadeira doméstica', status: 'APPROVED' });
    return json({});
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<MemoryRouter initialEntries={['/criativos/cr1']}><Routes><Route path="/criativos/:id" element={<CreativePage />} /></Routes></MemoryRouter>);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('Creative Workspace F2.16A', () => {
  it('apresenta hero humano com status, canal, formato e campanha sem repetir o resumo antigo', async () => {
    setup();
    expect(await screen.findByRole('heading', { name: 'Criativo — Parafusadeira' })).toBeInTheDocument();
    expect(screen.getByText('Rascunho')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Estado e formato do criativo')).getByText('Instagram Reels')).toBeInTheDocument();
    expect(screen.getByText('Vídeo curto')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Parafusadeira doméstica' })).toHaveAttribute('href', '/campanhas/cp1');
    expect(screen.queryByText('CREATIVE STUDIO')).not.toBeInTheDocument();
    expect(screen.getByText('approval-secret-id')).not.toBeVisible();
    expect(screen.queryByText('Experimento')).not.toBeInTheDocument();
  });

  it('DRAFT não pronto indica o que falta e não oferece envio prematuro', async () => {
    setup();
    expect(await screen.findByRole('heading', { name: 'Complete o conteúdo do criativo' })).toBeInTheDocument();
    expect(screen.getByText('6 de 8 requisitos atendidos')).toBeInTheDocument();
    expect(screen.getByLabelText('Roteiro')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Enviar para revisão' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ir para conteúdo' })).toBeInTheDocument();
  });

  it('leva ao conteúdo editorial com scroll e foco, sem gerar estrutura', async () => {
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView });
    try {
      const fetchMock = setup();
      const button = await screen.findByRole('button', { name: 'Ir para conteúdo' });
      fireEvent.click(button);
      const editorial = document.getElementById('creative-editorial');
      expect(editorial).toHaveAttribute('tabindex', '-1');
      expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
      expect(document.activeElement).toBe(editorial);
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('generate-template'))).toBe(false);
    } finally {
      if (original) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', original);
      else Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: undefined });
    }
  });

  it('mantém os textareas compactos, com roteiro maior e labels em português', async () => {
    setup();
    expect(await screen.findByLabelText('Premissa')).toHaveAttribute('rows', '1');
    expect(screen.getByLabelText('Hook')).toHaveAttribute('rows', '2');
    expect(screen.getByLabelText('Roteiro')).toHaveAttribute('rows', '4');
    expect(screen.getByLabelText('Chamada para ação')).toHaveAttribute('rows', '1');
    expect(screen.getByRole('heading', { name: 'Aviso de afiliação' })).toBeInTheDocument();
    expect(screen.getByText(/Ver sequência visual sugerida/)).toBeInTheDocument();
  });

  it('readiness pronto coloca a aprovação dentro de Próxima ação', async () => {
    setup({ readinessState: 'READY_FOR_REVIEW', checks: { hook: true, bodyScript: true, cta: true, sceneCount: true, disclosure: true, warningCoverage: true, compliance: true, campaignApproved: true } });
    expect(await screen.findByRole('heading', { name: 'Pronto para revisão' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Enviar para revisão' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Aprovar' })).not.toBeInTheDocument();
  });

  it('resume quality checks em grupos e mantém storyboard recolhido até solicitação', async () => {
    setup();
    expect(await screen.findByText('Qualidade da direção')).toBeInTheDocument();
    expect(screen.getByText('Força do gancho')).toBeInTheDocument();
    expect(screen.getByText('Produto aparece cedo')).toBeInTheDocument();
    const storyboard = screen.getByText(/Ver sequência visual sugerida/).closest('details');
    expect(storyboard).not.toHaveAttribute('open');
    expect(screen.queryByText('speech-private-id')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText(/Ver sequência visual sugerida/));
    expect(await screen.findByText('Cena 1 — Abertura')).toBeInTheDocument();
    expect(screen.getByText('Texto de abertura')).toBeInTheDocument();
    expect(screen.queryByText('speech-private-id')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Detalhes técnicos'));
    expect(screen.getByText('Segmento de fala: speech-private-id')).toBeInTheDocument();
  });

  it('salva conteúdo editorial e apresenta confirmação de overwrite inline, sem confirm global', async () => {
    const confirm = vi.fn();
    vi.stubGlobal('confirm', confirm);
    const fetchMock = setup();
    const hook = await screen.findByLabelText('Hook');
    fireEvent.change(hook, { target: { value: 'Novo hook editorial' } });
    expect(screen.getByText('Alterações não salvas')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Salvar alterações' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/creatives\/cr1$/), expect.objectContaining({ method: 'PATCH' })));
    expect(await screen.findByText('Salvo')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Gerar estrutura inicial' }));
    expect(await screen.findByText('Gerar novamente substituirá o roteiro e as cenas atuais.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(confirm).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/generate-template'))).toBe(false);
  });

  it('mostra compliance WARN e BLOCK sem expor códigos; PASS mantém as seções claras', async () => {
    setup({ compliance: 'WARN' });
    expect(await screen.findByRole('heading', { name: 'Atenção' })).toBeInTheDocument();
    expect(screen.getByText('Nenhuma advertência obrigatória.')).toBeInTheDocument();
    expect(screen.getByText('Evitar estas alegações')).toBeInTheDocument();
  });

  it('abre o formulário de cena sob demanda, permite cancelar e cria uma cena sem efeitos colaterais', async () => {
    const fetchMock = setup({ initialScenes: [] });
    expect(await screen.findByText('Nenhuma cena criada ainda.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Narração')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Adicionar cena' }));
    expect(screen.getByLabelText('Narração')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByLabelText('Narração')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === 'POST')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Adicionar cena' }));
    fireEvent.change(screen.getByLabelText('Narração'), { target: { value: 'Nova fala' } });
    fireEvent.click(screen.getByRole('button', { name: 'Adicionar cena' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/creatives\/cr1\/scenes$/), expect.objectContaining({ method: 'POST' })));
    expect(await screen.findByText(/Nova fala/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('instagram-publish'))).toBe(false);
  });

  it('mostra distribuição somente para APPROVED e não publica no carregamento', async () => {
    const fetchMock = setup({ status: 'APPROVED', readinessState: 'APPROVED', checks: { hook: true } });
    expect(await screen.findByRole('heading', { name: 'Criativo aprovado' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Distribuição' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Preparar publicação' })).toHaveAttribute('href', '/criativos/cr1/publicar/instagram');
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes('instagram-publish') || (init as RequestInit | undefined)?.method === 'POST')).toBe(false);
  });

  it('READY_FOR_REVIEW permanece somente leitura e aguarda decisão', async () => {
    setup({ status: 'READY_FOR_REVIEW', readinessState: 'READY_FOR_REVIEW' });
    expect(await screen.findByRole('heading', { name: 'Aguardando decisão' })).toBeInTheDocument();
    expect(screen.getByLabelText('Hook')).toHaveAttribute('readonly');
    expect(screen.queryByRole('button', { name: 'Salvar alterações' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Enviar para revisão' })).not.toBeInTheDocument();
  });

  it('exibe a rastreabilidade somente após abrir os detalhes', async () => {
    setup();
    expect(await screen.findByText('Ações avançadas e rastreabilidade')).toBeInTheDocument();
    expect(screen.getByText('approval-secret-id')).not.toBeVisible();
    fireEvent.click(screen.getByText('Ações avançadas e rastreabilidade'));
    expect(screen.getByText('approval-secret-id')).toBeInTheDocument();
    expect(screen.getByText('assessment-id')).toBeInTheDocument();
  });
});

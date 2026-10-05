import{fireEvent,render,screen,waitFor,within}from'@testing-library/react';
import{afterEach,describe,expect,it,vi}from'vitest';
import{MemoryRouter,Route,Routes}from'react-router-dom';
import{MediaProduction}from'../components/MediaProduction';
import{CreativeMediaPage}from'../pages/CreativeMedia';
vi.mock('../components/FormatDecision',()=>({FormatDecision:()=>null}));
vi.mock('../components/StaticProduction',()=>({StaticProduction:()=>null}));

const diagnostic={ffmpeg:{status:'AVAILABLE'},ffprobe:{status:'AVAILABLE'},tts:{status:'AVAILABLE'},storage:{status:'AVAILABLE'}};
const response=(body:unknown,status=200)=>Promise.resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}));
const asset=(id:string,candidateId='candidate-a',classification='HERO_IMAGE',active=true,provider='MERCADO_LIVRE')=>({id,assetType:'PRODUCT_IMAGE',ownerType:'CANDIDATE',ownerId:candidateId,logicalName:`Foto ${id}`,mimeType:'image/png',width:1080,height:1080,fileSizeBytes:12000,metadata:{classification,provider,...(provider==='MERCADO_LIVRE'?{sourceKind:'MERCADO_LIVRE_OFFICIAL_API',sourceEvidenceType:'CATALOG_PICTURE',sourceEvidenceId:`evidence-${id}`}:{})},active,createdAt:'2026-10-01T12:00:00Z'});
const bundle=(assets:ReturnType<typeof asset>[])=>({ownerId:'candidate-a',assetCount:assets.length,uniqueVisualGroups:assets.length,videoCount:0,detailCount:assets.filter(item=>item.metadata.classification==='DETAIL_IMAGE').length,heroCount:assets.filter(item=>item.metadata.classification==='HERO_IMAGE').length,diversityScore:assets.length*20,diversityLevel:assets.length>=4?'HIGH':assets.length>=2?'MEDIUM':'LOW',qualityCheck:assets.length>=3?'PASS':'WARNING',warning:assets.length>=3?null:'Limited source media',assets:assets.map((item,index)=>({assetId:item.id,mediaType:'PRODUCT_IMAGE',width:item.width,height:item.height,aspectRatio:1,hasAlpha:false,classification:item.metadata.classification,confidence:'HIGH',qualityScore:80,visualFingerprint:`fp:${item.id}`,duplicateGroup:`GROUP-${index}`,usableFor:['GENERAL'],warnings:[]}))});
const mediaState=(candidateId:string,assets:ReturnType<typeof asset>[])=>({candidateId,provider:'MERCADO_LIVRE',status:assets.some(item=>item.active&&item.metadata.provider==='MERCADO_LIVRE')?'AVAILABLE':'UNAVAILABLE',assetCount:assets.filter(item=>item.active&&item.metadata.provider==='MERCADO_LIVRE').length,assets:[]});
const queuedJob={id:'job-queued',creativeId:'creative-1',renderType:'PREVIEW',status:'QUEUED',attemptNumber:1,createdAt:'2026-10-01T12:00:00Z',actualDurationSeconds:null,outputSizeBytes:null,validationStatus:null,validationDetails:null,progressPercent:0,currentStage:null,currentSceneIndex:null,totalScenes:null,errorCode:null,errorMessage:null,completedAt:null};
type SetupOptions={candidateId?:string;assets?:ReturnType<typeof asset>[];jobList?:Record<string,unknown>[];handoffState?:string;syncResponse?:Record<string,unknown>;afterSyncAssets?:ReturnType<typeof asset>[];afterSyncBundle?:ReturnType<typeof bundle>;syncHandler?:()=>Promise<Response>;allAssetsForOwnerQuery?:boolean;candidateStateHandler?:()=>Promise<Response>};
function setup(options:SetupOptions={}){
  const candidateId=options.candidateId??'candidate-a';let localAssets=options.assets??[];let localBundle=options.afterSyncBundle??bundle(localAssets);let state=mediaState(candidateId,localAssets);const jobList=options.jobList??[];
  const handoff={state:options.handoffState??'READY_TO_CREATE',creativeId:'creative-1',creativeStatus:'APPROVED',renderType:'PREVIEW',creativeApprovalId:'approval-1',inputFingerprint:'prepared-fingerprint',mediaJobId:options.handoffState==='JOB_EXISTS'||options.handoffState==='ACTIVE_JOB_CONFLICT'?'job-queued':null,mediaJobStatus:options.handoffState==='JOB_EXISTS'||options.handoffState==='ACTIVE_JOB_CONFLICT'?jobList[0]?.status??'QUEUED':null,attemptNumber:1,previousMediaJobId:null,reasonCode:null,blockers:[],warnings:[]};
  const fetchMock=vi.fn(async(input:string|URL,init?:RequestInit)=>{const url=String(input),parsed=new URL(url),method=init?.method??'GET';
    if(url.includes('/media-jobs?'))return response(jobList);
    if(url.includes('/distribution-plan?'))return response({recommendations:[],recommendedSelection:[],publicationCandidates:[],roles:{primary:null},experimentId:null});
    if(url.includes('/media-handoff'))return response(handoff);
    if(url.endsWith('/media/diagnostics'))return response(diagnostic);
    if(parsed.pathname.endsWith('/product-media/sync')&&method==='POST'){
      const result=options.syncHandler?await options.syncHandler():await response(options.syncResponse??{candidateId,provider:'MERCADO_LIVRE',status:'AVAILABLE',reasonCode:null,sourcePictureCount:0,downloadedCount:0,reusedCount:0,skippedCount:0,failedCount:0,assets:[]});
      if(result.ok&&options.afterSyncAssets){localAssets=options.afterSyncAssets;localBundle=options.afterSyncBundle??bundle(localAssets);state=mediaState(candidateId,localAssets)}
      return result;
    }
    if(parsed.pathname.endsWith('/product-media'))return options.candidateStateHandler?options.candidateStateHandler():response(state);
    if(parsed.pathname.includes('/product-media-bundles/'))return response(localBundle);
    if(parsed.pathname.endsWith('/media-assets')&&method==='POST')return response({});
    if(url.includes('/media-assets?')){
      if(!options.allAssetsForOwnerQuery&&parsed.searchParams.get('ownerType')==='AVATAR')return response([]);
      const requestedActive=parsed.searchParams.get('active');
      const rows=options.allAssetsForOwnerQuery?localAssets:localAssets.filter(item=>item.ownerId===parsed.searchParams.get('ownerId'));
      return response(rows.filter(item=>String(item.active)===requestedActive));
    }
    if(/\/media-jobs\/[^/]+\/start$/.test(parsed.pathname))return response({detail:{code:'MEDIA_JOB_INPUT_STALE',message:'Dados desatualizados'}},409);
    if(parsed.pathname.includes('/media-jobs/from-creative/'))return response(queuedJob,201);
    return response({});
  });
  vi.stubGlobal('fetch',fetchMock);
  const view=render(<MemoryRouter><MediaProduction creativeId="creative-1" candidateId={candidateId}/></MemoryRouter>);
  return{fetchMock,view};
}

afterEach(()=>vi.unstubAllGlobals());
describe('workspace de fontes visuais do produto',()=>{
  it('carrega explicitamente o estado e identifica o loading da galeria',async()=>{
    let resolveState:(value:Response)=>void=()=>{};const pending=new Promise<Response>(resolve=>{resolveState=resolve});
    setup({candidateStateHandler:()=>pending});
    const gallery=screen.getByRole('region',{name:'Fontes visuais do produto'});
    expect(within(gallery).getByRole('status')).toHaveTextContent('Carregando as fontes visuais');
    expect(screen.getByRole('button',{name:'Sincronizar fotos do Mercado Livre'})).toBeDisabled();
    resolveState(await response(mediaState('candidate-a',[])));
    expect(await screen.findByText('Nenhuma imagem ativa disponível para este produto.')).toBeInTheDocument();
  });

  it('mostra imagens ativas, classificações, dimensões e origem usando conteúdo local e lazy loading',async()=>{
    const images=[asset('hero'),asset('alt-1','candidate-a','ALTERNATE_IMAGE'),asset('alt-2','candidate-a','ALTERNATE_IMAGE'),asset('detail','candidate-a','DETAIL_IMAGE'),asset('accessory','candidate-a','ACCESSORY_IMAGE'),asset('package','candidate-a','PACKAGE_IMAGE'),asset('feature','candidate-a','FEATURE_IMAGE'),asset('manual','candidate-a','CONTEXT_IMAGE',true,'MANUAL')];
    const{fetchMock}=setup({assets:images});
    expect(await screen.findByText('Foto hero')).toBeInTheDocument();
    expect(screen.getAllByRole('img')).toHaveLength(8);
    const gallery=screen.getByRole('region',{name:'Galeria de imagens do produto'});
    expect(within(gallery).getByText('Principal')).toBeInTheDocument();expect(within(gallery).getAllByText('Alternativa')).toHaveLength(2);expect(within(gallery).getByText('Detalhe')).toBeInTheDocument();expect(within(gallery).getAllByText('Mercado Livre')).toHaveLength(7);expect(within(gallery).getByText('Manual/Outra origem')).toBeInTheDocument();
    expect(screen.getAllByRole('img').every(image=>image.getAttribute('loading')==='lazy')).toBe(true);
    expect(screen.getAllByRole('img').every(image=>image.getAttribute('src')?.includes('/media-assets/')&&image.getAttribute('src')?.endsWith('/content'))).toBe(true);
    expect(screen.queryByText(/http2\.mlstatic|https:\/\//)).not.toBeInTheDocument();
    const productWorkspace=screen.getByRole('region',{name:'Fontes visuais do produto'});
    expect(within(productWorkspace).getByText('Pronto')).toBeInTheDocument();expect(within(productWorkspace).getByText('Imagens disponíveis').parentElement).toHaveTextContent('8');
    expect(fetchMock.mock.calls.some(([url])=>String(url).includes('/publication'))).toBe(false);
  });

  it('ordena destaque primeiro, imagens oficiais por posição e origem manual por último, mantendo inativas separadas',async()=>{
    const hero={...asset('hero','candidate-a','HERO_IMAGE',true,'MANUAL'),logicalName:'Destaque manual'};
    const officialSecond={...asset('official-2','candidate-a','ALTERNATE_IMAGE'),logicalName:'Mercado Livre — imagem 2',metadata:{...asset('official-2').metadata,position:1}};
    const officialFirst={...asset('official-1','candidate-a','ALTERNATE_IMAGE'),logicalName:'Mercado Livre — imagem 1',metadata:{...asset('official-1').metadata,position:0}};
    const manual={...asset('manual-last','candidate-a','CONTEXT_IMAGE',true,'MANUAL'),logicalName:'Foto manual'};
    const inactive=asset('inactive','candidate-a','DETAIL_IMAGE',false,'MERCADO_LIVRE');
    setup({assets:[officialSecond,manual,inactive,hero,officialFirst],afterSyncBundle:bundle([officialSecond,hero,officialFirst,manual])});
    const gallery=await screen.findByRole('region',{name:'Galeria de imagens do produto'});
    expect(gallery).toHaveClass('product-media-gallery');
    expect(Array.from(gallery.querySelectorAll('.product-media-card-copy>b')).map(node=>node.textContent)).toEqual(['Destaque manual','Mercado Livre — imagem 1','Mercado Livre — imagem 2','Foto manual']);
    expect(within(gallery).getAllByText('Mercado Livre')).toHaveLength(2);
    expect(screen.getByText('Imagens inativas (1)').closest('details')).not.toHaveAttribute('open');
    expect(gallery.querySelectorAll('.product-media-card')).toHaveLength(4);
    expect(within(screen.getByRole('region',{name:'Fontes visuais do produto'})).getByText('Imagens disponíveis').parentElement).toHaveTextContent('4');
  });

  it('sincroniza com botão protegido contra duplo clique sem alterar jobs ativos',async()=>{
    let releaseSync:(value:Response)=>void=()=>{};const pending=new Promise<Response>(resolve=>{releaseSync=resolve});
    const runningJob={...queuedJob,status:'RENDERING_SCENES'};
    const{fetchMock}=setup({handoffState:'ACTIVE_JOB_CONFLICT',jobList:[runningJob],syncHandler:()=>pending,afterSyncAssets:[asset('new-photo')],afterSyncBundle:bundle([asset('new-photo')])});
    const button=await screen.findByRole('button',{name:'Sincronizar fotos do Mercado Livre'});await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);fireEvent.click(button);
    expect(await screen.findByRole('button',{name:'Sincronizando…'})).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([url,init])=>String(url).endsWith('/product-media/sync')&&init?.method==='POST')).toHaveLength(1);
    releaseSync(await response({candidateId:'candidate-a',provider:'MERCADO_LIVRE',status:'AVAILABLE',reasonCode:null,sourcePictureCount:1,downloadedCount:1,reusedCount:0,skippedCount:0,failedCount:0,assets:[]}));
    expect(await screen.findByText(/1 imagem disponível\. 1 nova/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url])=>/\/media-jobs\/from-creative|\/start$|\/cancel$/.test(String(url)))).toBe(false);
  });

  it('apresenta a sincronização idempotente sem sugerir novas imagens',async()=>{
    const images=Array.from({length:8},(_,index)=>asset(`photo-${index}`,'candidate-a',index===0?'HERO_IMAGE':'ALTERNATE_IMAGE'));
    setup({assets:images,syncResponse:{candidateId:'candidate-a',provider:'MERCADO_LIVRE',status:'AVAILABLE',reasonCode:null,sourcePictureCount:8,downloadedCount:0,reusedCount:8,skippedCount:0,failedCount:0,assets:[]}});
    await screen.findByText('Foto photo-0');fireEvent.click(await screen.findByRole('button',{name:'Sincronizar fotos do Mercado Livre'}));
    expect(await screen.findByText('Nenhuma nova imagem. 8 imagens já estavam atualizadas.')).toBeInTheDocument();
  });

  it('explica falhas parciais e seus motivos sem expor códigos técnicos',async()=>{
    setup({syncResponse:{candidateId:'candidate-a',provider:'MERCADO_LIVRE',status:'PARTIAL',reasonCode:null,sourcePictureCount:8,downloadedCount:6,reusedCount:0,skippedCount:0,failedCount:2,failures:[{remotePictureId:'p1',code:'PRODUCT_MEDIA_DOWNLOAD_FAILED'},{remotePictureId:'p2',code:'PRODUCT_MEDIA_INVALID_CONTENT'}],assets:[]},afterSyncAssets:Array.from({length:6},(_,index)=>asset(`synced-${index}`))});
    await screen.findByText('Nenhuma imagem ativa disponível para este produto.');fireEvent.click(await screen.findByRole('button',{name:'Sincronizar fotos do Mercado Livre'}));
    expect(await screen.findByText('6 de 8 imagens disponíveis; 2 não puderam ser importadas.')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Ver detalhes das falhas'));
    expect(screen.getAllByText('Não foi possível baixar uma ou mais imagens.').length).toBeGreaterThan(0);
    expect(screen.getByText('Uma das imagens recebidas não era válida.')).toBeInTheDocument();
    expect(screen.queryByText(/PRODUCT_MEDIA_/)).not.toBeInTheDocument();
  });

  it('mostra estado vazio e mantém a preparação uma ação explícita',async()=>{
    const{fetchMock}=setup({syncResponse:{candidateId:'candidate-a',provider:'MERCADO_LIVRE',status:'UNAVAILABLE',reasonCode:'PRODUCT_MEDIA_SOURCE_NOT_FOUND',sourcePictureCount:0,downloadedCount:0,reusedCount:0,skippedCount:0,failedCount:0,assets:[]}});
    expect(await screen.findByText('Nenhuma imagem ativa disponível para este produto.')).toBeInTheDocument();
    expect(screen.getByText(/Não encontramos fotos oficiais do produto/)).toBeInTheDocument();
    expect(screen.getByRole('button',{name:'Preparar preview'})).toBeEnabled();
    expect(fetchMock.mock.calls.some(([url])=>String(url).includes('/media-jobs/from-creative/'))).toBe(false);
    expect(screen.getByText('Diagnóstico técnico').closest('details')).not.toHaveAttribute('open');
    fireEvent.click(screen.getByRole('button',{name:'Sincronizar fotos do Mercado Livre'}));
    expect(await screen.findByText('Não encontramos fotos oficiais para este produto. Atualize os dados do Mercado Livre e tente novamente.')).toBeInTheDocument();
  });

  it('trata HTTP 200 UNAVAILABLE como ausência de fotos, preserva assets e permite tentar novamente',async()=>{
    const manualAsset=asset('manual-kept','candidate-a','CONTEXT_IMAGE',true,'MANUAL');
    const{fetchMock}=setup({assets:[manualAsset],syncResponse:{candidateId:'candidate-a',provider:'MERCADO_LIVRE',status:'UNAVAILABLE',reasonCode:'PRODUCT_MEDIA_SOURCE_NOT_FOUND',sourcePictureCount:0,downloadedCount:0,reusedCount:0,skippedCount:0,failedCount:0,assets:[]}});
    expect(await screen.findByText('Foto manual-kept')).toBeInTheDocument();
    const readsBefore=fetchMock.mock.calls.filter(([url])=>String(url).includes('/candidates/candidate-a/product-media')&&!String(url).endsWith('/sync')).length;
    const button=screen.getByRole('button',{name:'Sincronizar fotos do Mercado Livre'});
    fireEvent.click(button);
    expect(await screen.findByText('Não encontramos fotos oficiais para este produto. Atualize os dados do Mercado Livre e tente novamente.')).toBeInTheDocument();
    expect(screen.queryByText(/imagem disponível\.|imagens disponíveis\./)).not.toBeInTheDocument();
    expect(screen.getByText('Foto manual-kept')).toBeInTheDocument();
    expect(button).toBeEnabled();
    expect(fetchMock.mock.calls.filter(([url])=>String(url).includes('/candidates/candidate-a/product-media')&&!String(url).endsWith('/sync'))).toHaveLength(readsBefore);
    expect(fetchMock.mock.calls.filter(([url,init])=>String(url).endsWith('/product-media/sync')&&init?.method==='POST')).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([url])=>/\/media-jobs\/from-creative|\/start$/.test(String(url)))).toBe(false);
    fireEvent.click(button);
    await waitFor(()=>expect(fetchMock.mock.calls.filter(([url,init])=>String(url).endsWith('/product-media/sync')&&init?.method==='POST')).toHaveLength(2));
    expect(fetchMock.mock.calls.some(([url])=>/\/media-jobs\/from-creative|\/start$/.test(String(url)))).toBe(false);
  });

  it('mantém fotos do catálogo utilizáveis mesmo quando o item vinculado está forbidden e permite produção limitada',async()=>{
    const catalogImage=asset('catalog-photo');
    setup({assets:[catalogImage],candidateStateHandler:()=>response({...mediaState('candidate-a',[catalogImage]),itemDetailsStatus:'FORBIDDEN',catalogProductStatus:'AVAILABLE'})});
    expect(await screen.findByText('Foto catalog-photo')).toBeInTheDocument();
    const productWorkspace=screen.getByRole('region',{name:'Fontes visuais do produto'});
    expect(within(productWorkspace).getByText('Limitado')).toBeInTheDocument();
    expect(screen.getAllByText(/Material visual limitado — o vídeo poderá repetir imagens/).length).toBeGreaterThan(0);
    expect(screen.getByRole('button',{name:'Preparar preview'})).toBeEnabled();
    expect(screen.queryByText(/FORBIDDEN|403/)).not.toBeInTheDocument();
  });

  it('não mistura as imagens do candidato B no workspace do candidato A',async()=>{
    const pageCandidateA=asset('candidate-a-photo','candidate-a');const pageCandidateB=asset('candidate-b-photo','candidate-b');
    const{fetchMock}=setup({candidateId:'candidate-a',assets:[pageCandidateA,pageCandidateB],allAssetsForOwnerQuery:true});
    expect(await screen.findByText('Foto candidate-a-photo')).toBeInTheDocument();
    expect(screen.queryByText('Foto candidate-b-photo')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url])=>String(url).includes('/candidates/candidate-a/product-media'))).toBe(true);
    expect(fetchMock.mock.calls.some(([url])=>String(url).includes('/candidates/candidate-b/'))).toBe(false);
  });

  it('resolve candidateId pelo relacionamento Creative → Campaign, sem inferir pelo título',async()=>{
    const linkedAsset=asset('linked-photo','candidate-from-campaign');const otherAsset=asset('unrelated-photo','candidate-other');
    const fetchMock=vi.fn(async(input:string|URL)=>{const url=String(input);if(url.endsWith('/creatives/cr-route'))return response({id:'cr-route',campaignId:'campaign-real',name:'Creative de parafusadeira',status:'APPROVED',targetChannel:'TIKTOK',contentType:'SHORT_VIDEO'});if(url.endsWith('/campaigns/campaign-real'))return response({id:'campaign-real',candidateId:'candidate-from-campaign',name:'Campanha editorial parafusadeira'});if(url.endsWith('/creatives/cr-route/scenes'))return response([]);if(url.includes('/media-jobs?'))return response([]);if(url.includes('/media-handoff'))return response({state:'READY_TO_CREATE',creativeId:'cr-route',creativeStatus:'APPROVED',renderType:'PREVIEW',mediaJobId:null,mediaJobStatus:null,blockers:[],warnings:[]});if(url.endsWith('/media/diagnostics'))return response(diagnostic);if(url.includes('/media-assets?'))return response([linkedAsset,otherAsset]);if(url.includes('/candidates/candidate-from-campaign/product-media'))return response(mediaState('candidate-from-campaign',[linkedAsset]));if(url.includes('/product-media-bundles/candidate-from-campaign'))return response(bundle([linkedAsset]));return response({})});
    vi.stubGlobal('fetch',fetchMock);render(<MemoryRouter initialEntries={['/criativos/cr-route/midia']}><Routes><Route path="/criativos/:id/midia" element={<CreativeMediaPage/>}/></Routes></MemoryRouter>);
    expect(await screen.findByText('Foto linked-photo')).toBeInTheDocument();expect(screen.queryByText('Foto unrelated-photo')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url])=>String(url).includes('/candidates/candidate-from-campaign/product-media'))).toBe(true);
    expect(fetchMock.mock.calls.some(([url])=>String(url).includes('/candidates/candidate-other/'))).toBe(false);
  });

  it('explica MEDIA_JOB_INPUT_STALE sem tentar preparar outra produção automaticamente',async()=>{
    const{fetchMock}=setup({handoffState:'JOB_EXISTS',jobList:[queuedJob]});
    fireEvent.click(await screen.findByRole('button',{name:'Iniciar renderização'}));fireEvent.click(screen.getByRole('button',{name:'Confirmar início'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('As fontes visuais foram alteradas depois que esta produção foi preparada. Prepare uma nova produção.');
    expect(fetchMock.mock.calls.some(([url])=>String(url).includes('/media-jobs/from-creative/'))).toBe(false);
  });
});

import{fireEvent,render,screen,waitFor}from'@testing-library/react';
import{afterEach,expect,it,vi}from'vitest';
import{StaticProduction}from'../components/StaticProduction';

const response=(body:unknown,status=200)=>Promise.resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}));
const plan={creativeId:'creative-1',format:'STATIC_CARD',dimensions:{width:1080,height:1350},layout:'PRODUCT_TOP_FEATURES_BOTTOM',assetIds:['asset-1'],sourceAssetId:'asset-1',headline:{type:'USE_CASE',text:'PRA USO EM CASA?'},features:[{attributeKey:'use_case',displayLabel:'Uso indicado',displayValue:'Pequenos reparos.',sourceType:'MANUAL_OPERATOR',sourceReference:'evidence-1',confidence:'HIGH',verified:true,icon:'GENERIC_FEATURE'}],cta:{type:'VER_DETALHES',text:'VER DETALHES'},qualityChecks:{STATIC_PRODUCT_PROMINENCE:'PASS',STATIC_FEATURE_PROVENANCE:'PASS'},formatRecommendation:{recommendedFormats:['STATIC_CARD'],reasons:['Mensagem direta.']}};
afterEach(()=>vi.unstubAllGlobals());
it('seleciona card estático, mostra provenance e renderiza o PNG retornado',async()=>{
 const fetchMock=vi.fn(async(input:string|URL,init?:RequestInit)=>{const url=String(input);if(url.includes('/static-plan'))return response(plan);if(url.includes('/static-preview')&&init?.method==='POST')return response({...plan,files:['static/creative-1/static_card/card_01.png']},201);return response({})});vi.stubGlobal('fetch',fetchMock);render(<StaticProduction creativeId="creative-1"/>);
 fireEvent.change(screen.getByLabelText('Formato'),{target:{value:'STATIC_CARD'}});expect(await screen.findByText('PRA USO EM CASA?')).toBeInTheDocument();expect(screen.getByText(/Pequenos reparos/)).toBeInTheDocument();expect(screen.getByText('Verificada')).toBeInTheDocument();fireEvent.click(screen.getByRole('button',{name:'Gerar card'}));await waitFor(()=>expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/static-preview'),expect.objectContaining({method:'POST'})));expect(await screen.findByAltText('Preview do card')).toHaveAttribute('src',expect.stringContaining('card_01.png'));
});
it('oferece vídeo curto, card estático e carrossel sem geração automática',()=>{
 const fetchMock=vi.fn();vi.stubGlobal('fetch',fetchMock);render(<StaticProduction creativeId="creative-1"/>);expect(screen.getByRole('option',{name:'Vídeo curto'})).toBeInTheDocument();expect(screen.getByRole('option',{name:'Card estático'})).toBeInTheDocument();expect(screen.getByRole('option',{name:'Carrossel'})).toBeInTheDocument();expect(fetchMock).not.toHaveBeenCalled();
});

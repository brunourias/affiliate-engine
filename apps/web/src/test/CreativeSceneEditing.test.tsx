import{fireEvent,render,screen,waitFor}from'@testing-library/react';
import{MemoryRouter,Route,Routes}from'react-router-dom';
import{afterEach,describe,expect,it,vi}from'vitest';
import{CreativePage}from'../pages/Creatives';

const creative={id:'cr1',campaignId:'cp1',experimentId:null,name:'Criativo',status:'DRAFT',contentType:'SHORT_VIDEO',targetChannel:'GENERIC',angleTypeSnapshot:null,objectiveSnapshot:'EDUCATION',editorialVerdictSnapshot:'WORTH_IT',priceVerdictSnapshot:'FAIR_PRICE',title:'Título',contentPremise:'Premissa',hook:'Hook seguro',bodyScript:'Roteiro seguro',cta:'Compare',estimatedDurationSeconds:20,disclosureText:'Afiliado',requiredWarnings:[],forbiddenClaims:['BEST_ON_MARKET_UNSUPPORTED'],generationMode:'MANUAL',variantGroup:null,parentCreativeId:null,variantLabel:null};
const original={id:'s1',creativeId:'cr1',orderIndex:0,sceneType:'PRODUCT',speaker:'NARRATOR',purpose:'BENEFIT',narrationText:'Texto seguro',onScreenText:'Resumo',visualInstruction:'Mostrar produto',avatarState:null,durationSeconds:4,requiredWarningCodes:[]};
const response=(body:unknown,status=200)=>Promise.resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}));

function setup(failPatch=false){let scene={...original};const fetchMock=vi.fn(async(input:string|URL,init?:RequestInit)=>{const url=String(input),method=init?.method??'GET';
  if(url.endsWith('/creatives/cr1/scenes/s1')&&method==='PATCH'){if(failPatch)return response({detail:'Falha ao salvar a cena'},500);const body=JSON.parse(String(init?.body));scene={...scene,...body};return response(scene)}
  if(url.endsWith('/creatives/cr1/scenes'))return response([scene]);
  if(url.endsWith('/creatives/cr1/readiness')){const blocked=/melhor parafusadeira do mercado/i.test(scene.narrationText??'');return response({state:'NOT_READY',checks:{},sceneCount:1,compliance:{status:blocked?'BLOCK':'PASS',reasons:blocked?[{code:'BEST_ON_MARKET_UNSUPPORTED',message:"Alegação de 'melhor do mercado' sem evidência suficiente."}]:[],requiredWarningCoverage:[]}})}
  if(url.endsWith('/creatives/cr1'))return response(creative);
  if(url.endsWith('/campaigns/cp1'))return response({id:'cp1',name:'Parafusadeira doméstica',status:'APPROVED'});
  return response({});
});vi.stubGlobal('fetch',fetchMock);render(<MemoryRouter initialEntries={['/criativos/cr1']}><Routes><Route path="/criativos/:id" element={<CreativePage/>}/></Routes></MemoryRouter>);return fetchMock}

afterEach(()=>vi.unstubAllGlobals());
describe('edição inline de cenas',()=>{
  it('abre os campos e cancelar descarta sem PATCH',async()=>{const fetchMock=setup();fireEvent.click(await screen.findByRole('button',{name:'Editar'}));expect(screen.getByLabelText('Tipo da cena')).toHaveValue('PRODUCT');expect(screen.getByLabelText('Apresentador')).toHaveValue('NARRATOR');expect(screen.getByLabelText('Propósito')).toHaveValue('BENEFIT');fireEvent.change(screen.getByLabelText('Narração'),{target:{value:'Rascunho descartado'}});fireEvent.click(screen.getByRole('button',{name:'Cancelar'}));expect(screen.getByText('Benefício — Texto seguro')).toBeInTheDocument();expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining('/scenes/s1'),expect.objectContaining({method:'PATCH'}))});
  it('salva o PATCH, atualiza cena e compliance sem alterar scroll',async()=>{const scrollTo=vi.fn();vi.stubGlobal('scrollTo',scrollTo);const fetchMock=setup();fireEvent.click(await screen.findByRole('button',{name:'Editar'}));fireEvent.change(screen.getByLabelText('Narração'),{target:{value:'Esta é a melhor parafusadeira do mercado.'}});fireEvent.change(screen.getByLabelText('Texto na tela'),{target:{value:'Comparativo'}});fireEvent.click(screen.getByRole('button',{name:'Salvar'}));await waitFor(()=>expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/scenes/s1'),expect.objectContaining({method:'PATCH',body:expect.stringContaining('melhor parafusadeira do mercado')})));expect(await screen.findByText('Benefício — Esta é a melhor parafusadeira do mercado.')).toBeInTheDocument();expect(screen.getByText('Bloqueado')).toBeInTheDocument();expect(screen.getByText("Alegação de 'melhor do mercado' sem evidência suficiente.")).toBeInTheDocument();expect(scrollTo).not.toHaveBeenCalled()});
  it('mantém edição aberta e mostra erro quando o PATCH falha',async()=>{setup(true);fireEvent.click(await screen.findByRole('button',{name:'Editar'}));fireEvent.change(screen.getByLabelText('Narração'),{target:{value:'Texto que não pode ser salvo'}});fireEvent.click(screen.getByRole('button',{name:'Salvar'}));expect(await screen.findByRole('alert')).toHaveTextContent('Falha ao salvar a cena');expect(screen.getByLabelText('Narração')).toHaveValue('Texto que não pode ser salvo')});
});

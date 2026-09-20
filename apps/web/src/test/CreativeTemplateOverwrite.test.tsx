import{fireEvent,render,screen,waitFor}from'@testing-library/react';
import{MemoryRouter,Route,Routes}from'react-router-dom';
import{afterEach,describe,expect,it,vi}from'vitest';
import{CreativePage}from'../pages/Creatives';

const creative={id:'cr1',campaignId:'cp1',experimentId:null,name:'Criativo',status:'DRAFT',contentType:'SHORT_VIDEO',targetChannel:'GENERIC',angleTypeSnapshot:null,objectiveSnapshot:'EDUCATION',editorialVerdictSnapshot:'WORTH_IT',priceVerdictSnapshot:'FAIR_PRICE',title:null,contentPremise:null,hook:null,bodyScript:null,cta:null,estimatedDurationSeconds:20,disclosureText:'Afiliado',requiredWarnings:[],forbiddenClaims:[],generationMode:'MANUAL',variantGroup:null,parentCreativeId:null,variantLabel:null};
const oldScene={id:'old',creativeId:'cr1',orderIndex:0,sceneType:'TEXT',speaker:'NONE',purpose:'HOOK',narrationText:'Cena antiga',onScreenText:null,visualInstruction:null,avatarState:null,durationSeconds:2,requiredWarningCodes:[]};
const newScenes=[{...oldScene,id:'new-1',narrationText:'Novo hook'},{...oldScene,id:'new-2',orderIndex:1,sceneType:'CTA',purpose:'CTA',narrationText:'Novo CTA'}];
const generated={...creative,title:'Parafusadeira doméstica: vale a pena?',contentPremise:'Análise segura',hook:'Novo hook',bodyScript:'Novo roteiro narrável.',cta:'Novo CTA',generationMode:'DETERMINISTIC_TEMPLATE'};
const json=(body:unknown,status=200)=>Promise.resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}));

function setup(initialScenes= [oldScene],fail=false){
  let scenes=[...initialScenes];
  const fetchMock=vi.fn(async(input:string|URL,init?:RequestInit)=>{const url=String(input),method=init?.method??'GET';
    if(url.endsWith('/creatives/cr1/scenes'))return json(scenes);
    if(url.endsWith('/creatives/cr1/readiness'))return json({state:'NOT_READY',checks:{},sceneCount:scenes.length,compliance:{status:'PASS',reasons:[],requiredWarningCoverage:[]}});
    if(url.endsWith('/creatives/cr1/generate-template')&&method==='POST'){if(fail)return json({detail:'Falha segura ao gerar template'},500);scenes=[...newScenes];return json(generated)}
    if(url.endsWith('/creatives/cr1'))return json(creative);
    if(url.endsWith('/campaigns/cp1'))return json({id:'cp1',name:'Campanha do candidato',status:'APPROVED'});
    return json({});
  });
  vi.stubGlobal('fetch',fetchMock);render(<MemoryRouter initialEntries={['/criativos/cr1']}><Routes><Route path="/criativos/:id" element={<CreativePage/>}/></Routes></MemoryRouter>);return fetchMock;
}

afterEach(()=>vi.unstubAllGlobals());
describe('overwrite do template criativo',()=>{
  it('gera diretamente quando não existem cenas',async()=>{const confirm=vi.fn();vi.stubGlobal('confirm',confirm);const fetchMock=setup([]);fireEvent.click(await screen.findByRole('button',{name:'Gerar estrutura inicial'}));await waitFor(()=>expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/generate-template'),expect.objectContaining({body:JSON.stringify({overwrite:false})})));expect(confirm).not.toHaveBeenCalled();expect(await screen.findByDisplayValue('Novo roteiro narrável.')).toBeInTheDocument()});
  it('cancela sem chamar a API e preserva o draft',async()=>{const confirm=vi.fn(()=>false);vi.stubGlobal('confirm',confirm);const fetchMock=setup();const title=await screen.findByLabelText('Título');fireEvent.change(title,{target:{value:'Meu draft'}});fireEvent.click(screen.getByRole('button',{name:'Gerar estrutura inicial'}));expect(confirm).toHaveBeenCalledWith('Este criativo já possui uma estrutura. Gerar novamente substituirá o roteiro e as cenas atuais. Deseja continuar?');expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining('/generate-template'),expect.anything());expect(title).toHaveValue('Meu draft')});
  it('confirma overwrite, atualiza campos e cenas sem navegar ou rolar',async()=>{vi.stubGlobal('confirm',vi.fn(()=>true));const scrollTo=vi.fn();vi.stubGlobal('scrollTo',scrollTo);const fetchMock=setup();fireEvent.click(await screen.findByRole('button',{name:'Gerar estrutura inicial'}));await waitFor(()=>expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/generate-template'),expect.objectContaining({body:JSON.stringify({overwrite:true})})));expect(await screen.findByDisplayValue('Parafusadeira doméstica: vale a pena?')).toBeInTheDocument();expect(screen.getByDisplayValue('Novo hook')).toBeInTheDocument();expect(await screen.findByText('Abertura — Novo hook')).toBeInTheDocument();expect(screen.queryByText('Abertura — Cena antiga')).not.toBeInTheDocument();expect(scrollTo).not.toHaveBeenCalled()});
  it('exibe falha da API e mantém o draft e as cenas',async()=>{vi.stubGlobal('confirm',vi.fn(()=>true));setup(undefined,true);const title=await screen.findByLabelText('Título');fireEvent.change(title,{target:{value:'Meu draft preservado'}});await waitFor(()=>expect(title).toHaveValue('Meu draft preservado'));fireEvent.click(screen.getByRole('button',{name:'Gerar estrutura inicial'}));expect(await screen.findByRole('alert')).toHaveTextContent('Falha segura ao gerar template');expect(title).toHaveValue('Meu draft preservado');expect(screen.getByText('Abertura — Cena antiga')).toBeInTheDocument()});
});

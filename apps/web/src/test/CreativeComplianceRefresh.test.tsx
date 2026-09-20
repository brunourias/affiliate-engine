import{fireEvent,render,screen,waitFor}from'@testing-library/react';
import{MemoryRouter,Route,Routes}from'react-router-dom';
import{afterEach,describe,expect,it,vi}from'vitest';
import{CreativePage}from'../pages/Creatives';

const base={id:'cr1',campaignId:'cp1',experimentId:null,name:'Criativo',status:'DRAFT',contentType:'SHORT_VIDEO',targetChannel:'GENERIC',angleTypeSnapshot:null,objectiveSnapshot:'EDUCATION',editorialVerdictSnapshot:'WORTH_IT',priceVerdictSnapshot:'FAIR_PRICE',title:'Título seguro',contentPremise:'Premissa',bodyScript:'Roteiro seguro',cta:'Compare',estimatedDurationSeconds:20,disclosureText:'Afiliado',requiredWarnings:[],forbiddenClaims:['BEST_ON_MARKET_UNSUPPORTED'],generationMode:'MANUAL',variantGroup:null,parentCreativeId:null,variantLabel:null};
const json=(body:unknown)=>Promise.resolve(new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}}));

afterEach(()=>vi.unstubAllGlobals());
describe('atualização do compliance após salvar',()=>{
  it('reflete PASS, BLOCK com motivo em pt-BR e PASS novamente',async()=>{let hook='Texto seguro';vi.stubGlobal('fetch',vi.fn(async(input:string|URL,init?:RequestInit)=>{const url=String(input),method=init?.method??'GET';
    if(url.endsWith('/creatives/cr1/scenes'))return json([]);
    if(url.endsWith('/creatives/cr1/readiness')){const blocked=/melhor parafusadeira do mercado/i.test(hook);return json({state:'NOT_READY',checks:{},sceneCount:0,compliance:{status:blocked?'BLOCK':'PASS',reasons:blocked?[{code:'BEST_ON_MARKET_UNSUPPORTED',message:"Alegação de 'melhor do mercado' sem evidência suficiente."}]:[],requiredWarningCoverage:[]}})}
    if(url.endsWith('/creatives/cr1')&&method==='PATCH'){hook=String(JSON.parse(String(init?.body)).hook);return json({...base,hook})}
    if(url.endsWith('/creatives/cr1'))return json({...base,hook});
    if(url.endsWith('/campaigns/cp1'))return json({id:'cp1',name:'Parafusadeira doméstica',status:'APPROVED'});
    return json({});
  }));render(<MemoryRouter initialEntries={['/criativos/cr1']}><Routes><Route path="/criativos/:id" element={<CreativePage/>}/></Routes></MemoryRouter>);
    const input=await screen.findByDisplayValue('Texto seguro');expect(await screen.findByText('Aprovado')).toBeInTheDocument();
    fireEvent.change(input,{target:{value:'Esta é a melhor parafusadeira do mercado.'}});expect(screen.getByText('Não salvo')).toBeInTheDocument();fireEvent.click(screen.getByRole('button',{name:'Salvar criativo'}));expect(await screen.findByText('Bloqueado')).toBeInTheDocument();expect(screen.getByText("Alegação de 'melhor do mercado' sem evidência suficiente.")).toBeInTheDocument();
    fireEvent.change(input,{target:{value:'Compare os recursos antes de decidir.'}});fireEvent.click(screen.getByRole('button',{name:'Salvar criativo'}));await waitFor(()=>expect(screen.getByText('Aprovado')).toBeInTheDocument());expect(screen.queryByText("Alegação de 'melhor do mercado' sem evidência suficiente.")).not.toBeInTheDocument();
  });
});

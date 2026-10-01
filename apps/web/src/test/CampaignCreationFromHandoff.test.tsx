import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { CampaignHandoffGate } from '../components/CampaignHandoffGate';

const json=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
const currentHandoff=(status='APPROVED',overrides:Record<string,unknown>={})=>({candidateId:'candidate-1',status,assessmentId:status==='APPROVED'?'assessment-2':null,assessmentVersion:status==='APPROVED'?2:null,reviewedAt:'2026-09-30T12:00:00Z',reason:'Operador aprovou',currentAssessmentId:'assessment-2',currentAssessmentVersion:2,isCurrentAssessment:status==='APPROVED',...overrides});
const campaign=(overrides:Record<string,unknown>={})=>({id:'campaign-1',candidateId:'candidate-1',assessmentId:'assessment-2',name:'Produto aprovado',status:'DRAFT',objective:'EDUCATION',editorialVerdictSnapshot:'WORTH_IT',trustGateSnapshot:'PASS',recommendationScoreSnapshot:null,opportunityScoreSnapshot:null,priceVerdictSnapshot:'UNKNOWN',campaignPriority:'UNKNOWN',targetAudience:null,editorialPositioning:null,primaryMessage:null,affiliateUrl:null,affiliateUrlSource:'MANUAL',affiliateUrlVerifiedAt:null,disclosureText:'Disclosure',ctaStrategy:null,requiresFinancialSpend:false,trustWarningsSnapshot:[],requiredDisclosures:[],requiredWarnings:[],forbiddenClaims:[],createdAt:'2026-09-30T12:00:00Z',updatedAt:'2026-09-30T12:00:00Z',approvedAt:null,rejectedAt:null,...overrides});
const state=(status='READY_TO_CREATE',overrides:Record<string,unknown>={})=>({state:status,campaignId:null,campaignName:null,campaignStatus:null,assessmentId:'assessment-2',assessmentVersion:2,reasonCode:null,...overrides});

function RouteText(){const location=useLocation();return <output data-testid="route">{location.pathname}</output>}
function mount({gateStatus='APPROVED',stateResponse=state(),postResponse={created:true,campaign:campaign()},postFailure=false,showStatus=true,compact=true}:{gateStatus?:string;stateResponse?:ReturnType<typeof state>;postResponse?:{created:boolean;campaign:ReturnType<typeof campaign>};postFailure?:boolean;showStatus?:boolean;compact?:boolean}={}){
  let releasePost:(value:Response)=>void=()=>undefined;
  const postWait=new Promise<Response>(resolve=>{releasePost=resolve});
  const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input);const method=init?.method??'GET';
    if(url.endsWith('/campaign-handoff')&&method==='PATCH')return json(currentHandoff(JSON.parse(String(init?.body)).status));
    if(url.endsWith('/campaign-handoff'))return json(currentHandoff(gateStatus));
    if(url.endsWith('/campaign-handoff/campaign'))return json(stateResponse);
    if(url.endsWith('/campaigns/from-handoff/candidate-1')&&method==='POST')return postFailure?json({detail:'ASSESSMENT_CHANGED'},409):postWait;
    if(url.endsWith('/campaigns/campaign-1'))return json(campaign());
    return json({});
  });
  vi.stubGlobal('fetch',fetchMock);
  render(<MemoryRouter initialEntries={['/curator/candidate-1']}><Routes><Route path="/curator/candidate-1" element={<><CampaignHandoffGate candidateId="candidate-1" status={gateStatus as never} onDone={vi.fn()} compact={compact} showStatus={showStatus}/><RouteText/></>}/><Route path="/campanhas/:id" element={<RouteText/>}/></Routes></MemoryRouter>);
  return {fetchMock,finishPost:()=>releasePost(json(postResponse))};
}
function postCalls(fetchMock:ReturnType<typeof vi.fn>){return fetchMock.mock.calls.filter(([url,init])=>String(url).includes('/campaigns/from-handoff/')&&(init as RequestInit|undefined)?.method==='POST')}

describe('Campaign creation from approved handoff',()=>{
  afterEach(()=>vi.unstubAllGlobals());

  it('loads READY_TO_CREATE without creating and uses the canonical handoff endpoint',async()=>{
    const {fetchMock,finishPost}=mount();
    expect(await screen.findByRole('button',{name:'Criar campanha'})).toBeInTheDocument();
    expect(postCalls(fetchMock)).toHaveLength(0);
    fireEvent.click(screen.getByRole('button',{name:'Criar campanha'}));
    await waitFor(()=>expect(postCalls(fetchMock)).toHaveLength(1));
    expect(String(postCalls(fetchMock)[0][0])).toContain('/campaigns/from-handoff/candidate-1');
    expect(postCalls(fetchMock).some(([url])=>String(url).includes('/from-assessment/'))).toBe(false);
    expect(JSON.parse(String((postCalls(fetchMock)[0][1] as RequestInit).body))).toEqual({});
    finishPost();
    expect(await screen.findByText('Campanha criada como rascunho.')).toBeInTheDocument();
    expect(screen.getByRole('link',{name:'Abrir campanha'})).toHaveAttribute('href','/campanhas/campaign-1');
  });

  it('treats created=false as replay and links to the existing campaign',async()=>{
    const {finishPost}=mount({postResponse:{created:false,campaign:campaign()}});
    fireEvent.click(await screen.findByRole('button',{name:'Criar campanha'}));finishPost();
    expect(await screen.findByText('A campanha desta análise já existe.')).toBeInTheDocument();
    expect(screen.getByRole('link',{name:'Abrir campanha'})).toHaveAttribute('href','/campanhas/campaign-1');
    expect(screen.getByTestId('route')).toHaveTextContent('/curator/candidate-1');
  });

  it('blocks rapid repeated clicks while create is pending',async()=>{
    const {fetchMock,finishPost}=mount();const button=await screen.findByRole('button',{name:'Criar campanha'});
    fireEvent.click(button);fireEvent.click(button);
    await waitFor(()=>expect(postCalls(fetchMock)).toHaveLength(1));
    expect(screen.getByRole('button',{name:'Criando…'})).toBeDisabled();finishPost();
    await screen.findByRole('link',{name:'Abrir campanha'});
  });

  it('loads an existing campaign without offering creation and translates its status',async()=>{
    const {fetchMock}=mount({stateResponse:state('CAMPAIGN_EXISTS',{campaignId:'campaign-1',campaignName:'Campanha existente',campaignStatus:'DRAFT'}),compact:false});
    expect(await screen.findByText('Campanha existente')).toBeInTheDocument();
    expect(screen.getByText('Rascunho')).toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'Criar campanha'})).not.toBeInTheDocument();
    expect(screen.getByRole('link',{name:'Abrir campanha'})).toHaveAttribute('href','/campanhas/campaign-1');
    expect(postCalls(fetchMock)).toHaveLength(0);
  });

  it('warns on multiple legacy campaigns and does not offer creation',async()=>{
    const {fetchMock}=mount({stateResponse:state('MULTIPLE_CAMPAIGNS')});
    expect(await screen.findByText('Existem múltiplas campanhas históricas para esta análise. A vinculação precisa ser revisada antes de continuar.')).toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'Criar campanha'})).not.toBeInTheDocument();expect(postCalls(fetchMock)).toHaveLength(0);
  });

  it.each(['STALE','REJECTED','NOT_DECIDED'])('%s never exposes campaign creation',async status=>{
    const {fetchMock}=mount({gateStatus:status,stateResponse:state('NOT_ELIGIBLE')});
    expect(screen.queryByRole('button',{name:'Criar campanha'})).not.toBeInTheDocument();expect(postCalls(fetchMock)).toHaveLength(0);
    if(status!=='NOT_DECIDED') await waitFor(()=>expect(fetchMock).toHaveBeenCalled());
  });

  it('explains assessment changes without retrying create',async()=>{
    const {fetchMock}=mount({postFailure:true});
    fireEvent.click(await screen.findByRole('button',{name:'Criar campanha'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('A análise comercial mudou. Revise a versão atual antes de criar a campanha.');
    expect(postCalls(fetchMock)).toHaveLength(1);
  });

  it('shows the handoff reason and reopens the decision without deleting campaign data',async()=>{
    const {fetchMock}=mount({stateResponse:state('CAMPAIGN_EXISTS',{campaignId:'campaign-1',campaignName:'Produto aprovado',campaignStatus:'DRAFT'})});
    expect(await screen.findByText('Motivo: Operador aprovou')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Reabrir decisão'}));
    await waitFor(()=>expect(fetchMock.mock.calls.some(([url,init])=>String(url).endsWith('/campaign-handoff')&&(init as RequestInit|undefined)?.method==='PATCH')).toBe(true));
    expect(screen.queryByRole('button',{name:'Criar campanha'})).not.toBeInTheDocument();
    expect(postCalls(fetchMock)).toHaveLength(0);
  });
});

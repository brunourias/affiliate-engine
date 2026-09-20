import{fireEvent,render,screen,waitFor}from'@testing-library/react';
import{MemoryRouter,Route,Routes}from'react-router-dom';
import{afterEach,describe,expect,it,vi}from'vitest';
import{CampaignCreativeAction}from'../components/CampaignCreativeAction';

function response(body:unknown,status=200){return Promise.resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}))}
function setup(status:string){const fetchMock=vi.fn(async(input:string|URL,init?:RequestInit)=>{const url=String(input);if(url.endsWith('/campaigns/c1'))return response({id:'c1',status});if(url.endsWith('/creatives/from-campaign/c1')&&init?.method==='POST')return response({id:'cr1'},201);return response({})});vi.stubGlobal('fetch',fetchMock);render(<MemoryRouter initialEntries={['/campanhas/c1']}><Routes><Route path="/campanhas/:id" element={<CampaignCreativeAction/>}/><Route path="/criativos/:id" element={<div>Criativo criado</div>}/></Routes></MemoryRouter>);return fetchMock}
afterEach(()=>vi.unstubAllGlobals());
describe('ação de criar criativo',()=>{
  it.each(['DRAFT','PENDING_APPROVAL','REJECTED','PAUSED','ARCHIVED'])('mantém botão realmente disabled em %s',async status=>{const fetchMock=setup(status);const button=await screen.findByRole('button',{name:'Criar criativo'});expect(button).toBeDisabled();fireEvent.click(button);expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining('/creatives/from-campaign/'),expect.anything())});
  it('habilita e cria quando a campanha está APPROVED',async()=>{const fetchMock=setup('APPROVED');const button=await screen.findByRole('button',{name:'Criar criativo'});expect(button).toBeEnabled();fireEvent.click(button);await waitFor(()=>expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/creatives/from-campaign/c1'),expect.objectContaining({method:'POST'})));expect(await screen.findByText('Criativo criado')).toBeInTheDocument()});
});

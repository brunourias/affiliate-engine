import{fireEvent,render,screen,waitFor}from'@testing-library/react';
import{afterEach,expect,it,vi}from'vitest';
import{FormatDecision}from'../components/FormatDecision';

const recommendations=[
 {format:'STATIC_CARD',priority:'HIGH',confidence:'HIGH',reasons:[{code:'STRONG_HERO_IMAGE',message:'Boa imagem principal disponível.'}],warnings:[],readiness:'READY',estimatedGenerationCost:'LOW',estimatedGenerationEffort:'LOW',inputFingerprint:'one',outputStatus:'OUTDATED'},
 {format:'CAROUSEL',priority:'HIGH',confidence:'HIGH',reasons:[{code:'DETAIL_IMAGE_AVAILABLE',message:'Existe imagem de detalhe.'}],warnings:[],readiness:'READY',estimatedGenerationCost:'LOW',estimatedGenerationEffort:'MEDIUM',inputFingerprint:'two',outputStatus:'UP_TO_DATE'},
 {format:'VIDEO_SHORT',priority:'MEDIUM',confidence:'LOW',reasons:[{code:'TECHNICAL_DEPENDENCY_UNAVAILABLE',message:'Dependência indisponível.'}],warnings:['TECHNICAL_DEPENDENCY_UNAVAILABLE'],readiness:'NOT_READY',estimatedGenerationCost:'MEDIUM',estimatedGenerationEffort:'HIGH',inputFingerprint:'three',outputStatus:'OUTDATED'},
];
const plan={creativeId:'cr1',experimentId:'exp1',distributionMode:'UNKNOWN',recommendedSelection:['STATIC_CARD','CAROUSEL'],selectedFormats:['STATIC_CARD','CAROUSEL'],roles:{primary:'STATIC_CARD',secondary:['CAROUSEL']},recommendations,publicationCandidates:[],channelCompatibility:{},automaticGeneration:false,publicationEnabled:false};
const response=(body:unknown)=>Promise.resolve(new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}}));
afterEach(()=>vi.unstubAllGlobals());
it('mostra recomendações, permite desmarcar e só prepara após confirmação',async()=>{
 const fetchMock=vi.fn(async(_input:string|URL,init?:RequestInit)=>response(init?.method==='POST'?{...plan,selectedFormats:['CAROUSEL']}:plan));vi.stubGlobal('fetch',fetchMock);render(<FormatDecision creativeId="cr1"/>);
 expect(await screen.findByRole('checkbox',{name:'Card estático'})).toBeInTheDocument();expect(screen.getAllByText('Prioridade: Alta')).toHaveLength(2);expect(screen.getByText('Não pronto')).toBeInTheDocument();expect(fetchMock).toHaveBeenCalledTimes(1);
 fireEvent.click(screen.getByRole('checkbox',{name:'Card estático'}));expect(fetchMock).toHaveBeenCalledTimes(1);fireEvent.click(screen.getByRole('button',{name:'Preparar formatos selecionados'}));
 await waitFor(()=>expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining('/distribution-plan'),expect.objectContaining({method:'POST',body:JSON.stringify({selectedFormats:['CAROUSEL'],experimentId:'exp1',distributionMode:'UNKNOWN'})})));expect(await screen.findByText('Plano de formatos preparado. Nenhuma mídia foi gerada.')).toBeInTheDocument();
});

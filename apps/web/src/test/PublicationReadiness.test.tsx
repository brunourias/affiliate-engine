import{fireEvent,render,screen,waitFor}from'@testing-library/react';
import{afterEach,expect,it,vi}from'vitest';
import{PublicationReadinessPanel}from'../components/PublicationReadiness';
const base={publicationCandidateId:'pc1',creativeId:'cr1',channel:'TIKTOK',distributionMode:'PAID_AD',placement:'TIKTOK_IN_FEED',format:'CAROUSEL',assetFiles:['a','b','c'],channelVariantFingerprint:'v1',audioPlan:{status:'AUDIO_MISSING',mode:'NONE'},disclosurePlan:{requirementStatus:'UNKNOWN',status:'MISSING',manualReviewRequired:true},destinationUrl:'https://example.com',affiliateUrl:'https://example.com',approvalStatus:'APPROVED',warnings:[],blockers:[{code:'AUDIO_REQUIRED',severity:'BLOCKER',status:'OPEN',message:'Adicione áudio.',source:'AUDIO_PROFILE'},{code:'DISCLOSURE_REQUIREMENT_UNKNOWN',severity:'BLOCKER',status:'OPEN',message:'Revise o disclosure.',source:'DISCLOSURE_PROFILE'}],readinessStatus:'BLOCKED',manualReviewRequired:true,packageFingerprint:'f1',publicationEnabled:false as const};
const response=(body:unknown)=>Promise.resolve(new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}}));afterEach(()=>vi.unstubAllGlobals());
it('explica blockers e prepara pacote com seleção futura sem publicar',async()=>{
 const fetchMock=vi.fn(async(input:string|URL,init?:RequestInit)=>response(String(input).includes('/media-assets?')?[]:init?.method==='POST'?{...base,audioPlan:{status:'AUDIO_PLATFORM_SELECTION_REQUIRED',mode:'PLATFORM'},warnings:[{code:'AUDIO_PLATFORM_SELECTION_REQUIRED',message:'Selecione música comercial na plataforma antes de publicar.',source:'AUDIO_PLAN'}],blockers:base.blockers.slice(1)}:base));vi.stubGlobal('fetch',fetchMock);render(<PublicationReadinessPanel creativeId="cr1"/>);
 expect(await screen.findByText('Adicione áudio.')).toBeInTheDocument();
 expect(screen.getByRole('heading',{name:'Prontidão para publicação'})).toBeInTheDocument();
 fireEvent.click(screen.getByLabelText(/TikTok Commercial Music Library/));fireEvent.change(screen.getByPlaceholderText(/Este conteúdo contém/),{target:{value:'Texto manual'}});fireEvent.click(screen.getByRole('button',{name:'Preparar pacote de publicação'}));
 await waitFor(()=>expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/publication-package'),expect.objectContaining({method:'POST',body:expect.stringContaining('TIKTOK_CML')})));
 expect(await screen.findByText(/Nenhuma publicação foi realizada/)).toBeInTheDocument();
});

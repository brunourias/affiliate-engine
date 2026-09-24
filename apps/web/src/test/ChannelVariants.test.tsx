import{fireEvent,render,screen,waitFor}from'@testing-library/react';
import{afterEach,expect,it,vi}from'vitest';
import{ChannelVariants}from'../components/ChannelVariants';

const item={sourceCreativeId:'cr1',sourceFormat:'CAROUSEL',channel:'TIKTOK',distributionMode:'PAID_AD',placement:'TIKTOK_IN_FEED',profileId:'TIKTOK_CAROUSEL_PAID_V1',profile:{profileId:'TIKTOK_CAROUSEL_PAID_V1',profileVersion:'1',channel:'TIKTOK',distributionMode:'PAID_AD',placement:'TIKTOK_IN_FEED',creativeFormat:'CAROUSEL',aspectRatio:'9:16',width:720,height:1280,safeAreas:{top:80,bottom:120,left:40,right:40},fileTypes:['PNG'],audioRequirement:'REQUIRED',compatibility:'SUPPORTED_WITH_LIMITATIONS',source:'TIKTOK_ADS_DOCUMENTATION',lastReviewedAt:'2026-09-24'},adaptationStatus:'NOT_GENERATED',warnings:[]};
const response=(body:unknown,status=200)=>Promise.resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}));
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks()});
it('lista a variante e só renderiza após confirmação explícita',async()=>{
 const fetchMock=vi.fn(async(_input:string|URL,init?:RequestInit)=>response(init?.method==='POST'?{...item,adaptationStatus:'UP_TO_DATE',files:['channel_variants/cr1/TIKTOK_CAROUSEL_PAID_V1/card_01.png']}:[item]));vi.stubGlobal('fetch',fetchMock);const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);render(<ChannelVariants creativeId="cr1"/>);
 expect(await screen.findByText('TikTok — Carrossel')).toBeInTheDocument();expect(screen.getByText('9:16 · 720×1280')).toBeInTheDocument();expect(fetchMock).toHaveBeenCalledTimes(1);fireEvent.click(screen.getByRole('button',{name:'Gerar variante'}));expect(confirm).toHaveBeenCalled();expect(fetchMock).toHaveBeenCalledTimes(1);
 confirm.mockReturnValue(true);fireEvent.click(screen.getByRole('button',{name:'Gerar variante'}));await waitFor(()=>expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/channel-variants/render'),expect.objectContaining({method:'POST'})));
});

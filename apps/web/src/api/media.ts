import type{DistributionPlan,FormatDecision,MediaAsset,MediaDiagnostics,MediaJob,ProductMediaBundle,StaticCreativePlan}from'../types';
import{apiErrorMessage}from'../lib/apiError';

export const MEDIA_BASE=import.meta.env.VITE_API_URL??'http://127.0.0.1:8000/api/v1';
async function req<T>(path:string,init?:RequestInit):Promise<T>{const response=await fetch(MEDIA_BASE+path,init);if(!response.ok){const body:unknown=await response.json().catch(()=>null);throw new Error(apiErrorMessage(body,response.status))}return response.json()as Promise<T>}
export const mediaApi={
  diagnostics:()=>req<MediaDiagnostics>('/media/diagnostics'),
  jobs:(creativeId:string)=>req<MediaJob[]>('/media-jobs?creativeId='+encodeURIComponent(creativeId)),
  job:(id:string)=>req<MediaJob>('/media-jobs/'+id),
  create:(creativeId:string,renderType:'PREVIEW'|'STANDARD')=>req<MediaJob>('/media-jobs/from-creative/'+creativeId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({renderType})}),
  start:(id:string)=>req<MediaJob>('/media-jobs/'+id+'/start',{method:'POST'}),
  cancel:(id:string)=>req<MediaJob>('/media-jobs/'+id+'/cancel',{method:'POST'}),
  assets:async(ownerId:string)=>{const encoded=encodeURIComponent(ownerId),groups=await Promise.all([req<MediaAsset[]>('/media-assets?ownerId='+encoded+'&active=true'),req<MediaAsset[]>('/media-assets?ownerId='+encoded+'&active=false'),req<MediaAsset[]>('/media-assets?ownerType=AVATAR&active=true'),req<MediaAsset[]>('/media-assets?ownerType=AVATAR&active=false')]);return[...new Map(groups.flat().map(asset=>[asset.id,asset])).values()]},
  productBundle:async(ownerId:string)=>{const value=await req<ProductMediaBundle>('/product-media-bundles/'+encodeURIComponent(ownerId));if(!Array.isArray(value.assets))throw new Error('Resumo de mídia indisponível');return value},
  formatDecision:(creativeId:string)=>req<FormatDecision>('/creatives/'+creativeId+'/format-decision'),
  distributionPlan:(creativeId:string,distributionMode:'ORGANIC'|'PAID_AD'|'UNKNOWN'='UNKNOWN')=>req<DistributionPlan>('/creatives/'+creativeId+'/distribution-plan?distributionMode='+distributionMode),
  saveDistributionPlan:(creativeId:string,selectedFormats:string[],experimentId?:string,distributionMode:'ORGANIC'|'PAID_AD'|'UNKNOWN'='UNKNOWN')=>req<DistributionPlan>('/creatives/'+creativeId+'/distribution-plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selectedFormats,experimentId,distributionMode})}),
  staticPlan:(creativeId:string,format:'STATIC_CARD'|'CAROUSEL')=>req<StaticCreativePlan>('/creatives/'+creativeId+'/static-plan?format='+format),
  staticPreview:(creativeId:string,format:'STATIC_CARD'|'CAROUSEL')=>req<StaticCreativePlan>('/creatives/'+creativeId+'/static-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({format})}),
  staticContentUrl:(creativeId:string,format:'STATIC_CARD'|'CAROUSEL',file:string)=>MEDIA_BASE+'/creatives/'+creativeId+'/static-content/'+format.toLowerCase()+'/'+encodeURIComponent(file),
  upload:(form:FormData)=>req<MediaAsset>('/media-assets',{method:'POST',body:form}),
  removeAsset:(id:string)=>req<MediaAsset>('/media-assets/'+id,{method:'DELETE'}),
  activateAsset:(id:string)=>req<MediaAsset>('/media-assets/'+id+'/activate',{method:'POST'}),
  deleteAsset:async(id:string)=>{const response=await fetch(MEDIA_BASE+'/media-assets/'+id+'/permanent',{method:'DELETE'});if(!response.ok){const body:unknown=await response.json().catch(()=>null);throw new Error(apiErrorMessage(body,response.status))}},
  contentUrl:(id:string,download=false)=>MEDIA_BASE+'/media-jobs/'+id+'/content'+(download?'?download=true':''),
  assetUrl:(id:string)=>MEDIA_BASE+'/media-assets/'+id+'/content',
};

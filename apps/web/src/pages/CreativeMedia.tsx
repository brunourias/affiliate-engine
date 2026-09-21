import{useCallback}from'react';
import{useParams}from'react-router-dom';
import{creativesApi}from'../api/creatives';
import{campaignsApi}from'../api/campaigns';
import{MediaProduction}from'../components/MediaProduction';
import{useLoad}from'../hooks';

export function CreativeMediaPage(){const{id=''}=useParams();const load=useCallback(async()=>{const creative=await creativesApi.get(id);if(creative.status!=='APPROVED')return null;const[campaign,scenes]=await Promise.all([campaignsApi.get(creative.campaignId),creativesApi.scenes(id)]);return{creative,campaign,requiresVoice:scenes.some(scene=>Boolean(scene.narrationText)&&scene.speaker!=='NONE')}},[id]);const{data}=useLoad(load);if(!data)return null;return <MediaProduction creativeId={data.creative.id} candidateId={data.campaign.candidateId} requiresVoice={data.requiresVoice}/>}

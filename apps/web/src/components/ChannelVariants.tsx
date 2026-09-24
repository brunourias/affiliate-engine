import{useCallback,useEffect,useState}from'react';
import{mediaApi}from'../api/media';
import type{ChannelVariant}from'../types';
import'./ChannelVariants.css';

const channelLabels:Record<string,string>={TIKTOK:'TikTok',INSTAGRAM:'Instagram',FACEBOOK:'Facebook',YOUTUBE_SHORTS:'YouTube Shorts'};
const formatLabels:Record<string,string>={STATIC_CARD:'Card estático',CAROUSEL:'Carrossel',VIDEO_SHORT:'Vídeo curto'};
const statusLabels:Record<string,string>={NOT_GENERATED:'Não gerado',UP_TO_DATE:'Atualizado',OUTDATED:'Desatualizado',GENERATING:'Gerando',FAILED:'Falhou'};

export function ChannelVariants({creativeId}:{creativeId:string}){
 const[items,setItems]=useState<ChannelVariant[]>([]),[busy,setBusy]=useState(''),[error,setError]=useState('');
 const load=useCallback(()=>mediaApi.channelVariants(creativeId).then(setItems).catch(e=>setError(e instanceof Error?e.message:'Não foi possível carregar as variantes.')),[creativeId]);
 useEffect(()=>{void load()},[load]);
 const renderVariant=async(item:ChannelVariant)=>{if(!item.profile.profileId||!window.confirm('Gerar esta variante técnica agora?'))return;setBusy(item.profile.profileId);setError('');try{await mediaApi.renderChannelVariant(creativeId,{channel:item.profile.channel,distributionMode:item.profile.distributionMode,placement:item.profile.placement,creativeFormat:item.profile.creativeFormat});await load()}catch(e){setError(e instanceof Error?e.message:'Não foi possível gerar a variante.')}finally{setBusy('')}};
 return <section className="panel channel-variants"><h2>Variantes por canal</h2><p className="muted">Adaptações técnicas preservam texto, CTA, assets e provenance do criativo aprovado.</p>{error&&<p role="alert" className="inline-error">{error}</p>}<div className="variant-grid">{items.map(item=><article key={item.profile.profileId}><strong>{channelLabels[item.profile.channel]??item.profile.channel} — {formatLabels[item.profile.creativeFormat]??item.profile.creativeFormat}</strong><span>{item.profile.aspectRatio} · {item.profile.width}×{item.profile.height}</span><span>Status: {statusLabels[item.adaptationStatus]??item.adaptationStatus}</span><small>{item.profile.placement.replaceAll('_',' ')}</small>{item.files&&item.profileId&&<div className="variant-preview">{item.files.map(file=><img key={file} src={mediaApi.channelVariantContentUrl(creativeId,item.profileId!,file)} alt="Preview da variante"/>)}</div>}<button type="button" className="secondary-button" disabled={Boolean(busy)||item.adaptationStatus==='UP_TO_DATE'} onClick={()=>renderVariant(item)}>{busy===item.profile.profileId?'Gerando…':'Gerar variante'}</button></article>)}</div></section>;
}

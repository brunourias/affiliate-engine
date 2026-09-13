import type {ReactNode} from 'react';
export function Badge({children,tone='neutral'}:{children:ReactNode;tone?:string}){return <span className={`badge ${tone}`}>{children}</span>}
export function Section({title,aside,children}:{title:string;aside?:ReactNode;children:ReactNode}){return <section className="panel"><header className="panel-head"><h2>{title}</h2>{aside}</header>{children}</section>}
export function Empty({children}:{children:ReactNode}){return <div className="empty">{children}</div>}
export function Loading(){return <div className="state"><span className="spinner"/>Carregando dados reais…</div>}
export function ErrorState({error,retry}:{error:Error;retry:()=>void}){return <div className="error-state"><b>Não foi possível carregar.</b><span>{error.message}</span><button onClick={retry}>Tentar novamente</button></div>}
export const money=(cents:number)=>new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(cents/100);
export const date=(value:string|null)=>value?new Intl.DateTimeFormat('pt-BR',{dateStyle:'short',timeStyle:'short',timeZone:'America/Sao_Paulo'}).format(new Date(value)):'—';
export const statusTone=(s:string)=>['COMPLETED','APPROVED','SUCCESS','healthy'].includes(s)?'success':['FAILED','REJECTED','ERROR','CRITICAL'].includes(s)?'danger':['PENDING','WARNING'].includes(s)?'warning':['RUNNING'].includes(s)?'info':'neutral';

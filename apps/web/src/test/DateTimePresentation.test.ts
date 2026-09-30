import{describe,expect,it}from'vitest';
import{formatDateTime,label,statusTone}from'../lib/presentation';

describe('formatação global de data e hora',()=>{
  it.each(['2026-09-20T11:49:00Z','2026-09-20T11:49:00+00:00','2026-09-20T11:49:00'])("converte o instante UTC %s para São Paulo",value=>{
    expect(formatDateTime(value)).toBe('20/09/2026, 08:49');
  });
  it('mantém ausência de data como travessão',()=>expect(formatDateTime(null)).toBe('—'));
  it('traduz prioridades de triagem sem expor enums internos',()=>{
    expect(label('TRIAGE_HIGH')).toBe('Alta prioridade');
    expect(label('TRIAGE_MEDIUM')).toBe('Média prioridade');
    expect(label('TRIAGE_LOW')).toBe('Baixa prioridade');
  });
  it('traduz evidências parciais sem expor o enum interno',()=>expect(label('PARTIAL_EVIDENCE')).toBe('Evidências parciais'));
  it('usa fallback legível para um enum ainda sem rótulo dedicado',()=>expect(label('SOME_FUTURE_STATUS')).toBe('Some future status'));
  it('trata campo de status ausente sem quebrar a tela',()=>expect(label(undefined)).toBe('Não informado'));
  it('apresenta pendências comerciais como atenção, sem tratá-las como falha',()=>{
    expect(statusTone('WAITING_FOR_OFFER')).toBe('warning');
    expect(statusTone('EVIDENCE_PARTIAL')).toBe('warning');
    expect(statusTone('ASSESSMENT_AVAILABLE')).toBe('success');
  });
});

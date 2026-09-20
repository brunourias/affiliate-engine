import{describe,expect,it}from'vitest';
import{formatDateTime}from'../lib/presentation';

describe('formatação global de data e hora',()=>{
  it.each(['2026-09-20T11:49:00Z','2026-09-20T11:49:00+00:00','2026-09-20T11:49:00'])("converte o instante UTC %s para São Paulo",value=>{
    expect(formatDateTime(value)).toBe('20/09/2026, 08:49');
  });
  it('mantém ausência de data como travessão',()=>expect(formatDateTime(null)).toBe('—'));
});

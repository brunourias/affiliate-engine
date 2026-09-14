type ErrorBody = { detail?: unknown; message?: unknown };

function text(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value;
  if (Array.isArray(value)) {
    const messages = value.map(item => {
      if (typeof item === 'string') return item;
      if (item && typeof item === 'object' && 'msg' in item && typeof item.msg === 'string') return item.msg;
      return null;
    }).filter((item): item is string => Boolean(item));
    return messages.length ? messages.join(' ') : null;
  }
  return null;
}

export function apiErrorMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object') {
    const candidate = body as ErrorBody;
    return text(candidate.detail) ?? text(candidate.message) ?? `Não foi possível concluir a solicitação (HTTP ${status}).`;
  }
  return `Não foi possível concluir a solicitação (HTTP ${status}).`;
}

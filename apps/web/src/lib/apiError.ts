type ErrorBody = { detail?: unknown; message?: unknown };

export class ApiRequestError extends Error {
  constructor(message: string, readonly status: number, readonly code: string | null) {
    super(message);
    this.name = "ApiRequestError";
  }
}

export function apiRequestError(body: unknown, status: number): ApiRequestError {
  let code: string | null = null;
  if (body && typeof body === "object") {
    const detail = (body as ErrorBody).detail;
    if (detail && typeof detail === "object" && "code" in detail && typeof detail.code === "string") code = detail.code;
  }
  return new ApiRequestError(apiErrorMessage(body, status), status, code);
}

function text(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value;
  if (value && typeof value === 'object' && 'message' in value && typeof value.message === 'string' && value.message.trim()) return value.message;
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

export interface StreamEvent {
  type: string;
  content?: string;
  sources?: any[];
  images?: any[];
  fallback?: boolean;
  diagnostics?: {
    request_id?: string;
    model?: string;
    finish_reason?: string;
    answer_chars?: number;
    reasoning_chars?: number;
    refusal_chars?: number;
    usage?: Record<string, number>;
    error_type?: string;
    fallback_reason?: string;
  } | null;
}

export async function consumeChatStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: StreamEvent) => void,
  idleTimeoutMs = 120000
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finished = false;
  let failed = false;
  let hasAnswer = false;

  const dispatch = (frame: string) => {
    const payload = frame.split(/\r?\n/)
      .filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).replace(/^ /, ''))
      .join('\n');
    if (!payload || finished) return;
    const event: StreamEvent = JSON.parse(payload);
    if (event.type === 'error') failed = true;
    if (['answer', 'answer_complete', 'answer_chunk'].includes(event.type) && event.content?.trim()) {
      hasAnswer = true;
    }
    if (event.type === 'done') {
      if (!failed && !hasAnswer) throw new Error('未收到有效答案，请重试。');
      finished = true;
    }
    onEvent(event);
  };

  try {
    while (!finished) {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const next = await Promise.race([
        reader.read(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error('等待回复超时，请重试。')), idleTimeoutMs);
        }),
      ]).finally(() => clearTimeout(timer));
      buffer += decoder.decode(next.value, { stream: !next.done });
      let boundary: RegExpExecArray | null;
      while ((boundary = /\r?\n\r?\n/.exec(buffer)) !== null) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        dispatch(frame);
      }
      if (next.done) {
        if (!finished) throw new Error('连接提前中断，回复可能不完整，请重试。');
        break;
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

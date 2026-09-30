import axios from 'axios';
import { consumeChatStream } from './stream';
import type { ChatResponse, SearchResponse, KnowledgeBaseStats, AnswerDiagnostics, PdfOcrMeta } from '../types';

// 创建 axios 实例
const apiClient = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器 - 添加用户部门信息
apiClient.interceptors.request.use((config) => {
  const userDept = localStorage.getItem('user_dept');
  if (userDept && config.params) {
    config.params.user_dept = userDept;
  }
  return config;
});

// 响应拦截器 - 统一错误处理
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

// API 服务
export const api = {
  // 问答接口（支持会话）
  async chat(query: string, topK: number = 3, enableIntent: boolean = true, sessionId?: string): Promise<ChatResponse> {
    const response = await apiClient.post<ChatResponse>('/qa', null, {
      params: {
        query,
        top_k: topK,
        enable_intent: enableIntent,
        session_id: sessionId,
      },
    });
    return response.data;
  },

  // 流式问答接口
  async streamChat(
    query: string,
    enableIntent: boolean = true,
    sessionId: string | null,
    onThinking: (text: string) => void,
    onAnswerChunk: (text: string) => void,
    onAnswer: (data: {
      content: string;
      sources: any[];
      images: any[];
      fallback?: boolean;
      diagnostics?: AnswerDiagnostics | null;
    }) => void,
    onError: (error: string) => void,
    onDone: () => void
  ): Promise<void> {
    const userDept = localStorage.getItem('user_dept');
    const params = new URLSearchParams({
      question: query,
      enable_intent: enableIntent.toString(),
    });

    if (userDept) {
      params.append('user_dept', userDept);
    }

    if (sessionId) {
      params.append('session_id', sessionId);
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120000);
    const response = await fetch(`/api/qa/stream?${params.toString()}`, {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Accept': 'text/event-stream',
      },
    }).finally(() => clearTimeout(timer));

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    if (!response.body) throw new Error('未收到响应数据。');
    await consumeChatStream(response.body, data => {
      switch (data.type) {
        case 'thinking':
          onThinking(data.content || '');
          break;
        case 'answer_chunk':
          onAnswerChunk(data.content || '');
          break;
        case 'answer':
        case 'answer_complete':
          onAnswer({
            content: data.content || '',
            sources: data.sources || [],
            images: data.images || [],
            fallback: data.fallback,
            diagnostics: data.diagnostics,
          });
          break;
        case 'error':
          onError(data.content || '生成失败，请重试。');
          break;
        case 'done':
          onDone();
          break;
      }
    });
  },

  // 搜索接口
  async search(query: string, topK: number = 5, enableIntent: boolean = true): Promise<SearchResponse> {
    const response = await apiClient.post<SearchResponse>('/search', null, {
      params: {
        query,
        top_k: topK,
        enable_intent: enableIntent,
      },
    });
    return response.data;
  },

  // 上传文档
  async uploadFile(
    file: File,
    chunkStrategy: string = 'auto',
    chunkSize?: number,
    chunkOverlap?: number,
  ): Promise<any> {
    const formData = new FormData();
    formData.append('file', file);
    const params: Record<string, string | number> = { chunk_strategy: chunkStrategy };
    if (chunkSize !== undefined) params.chunk_size = chunkSize;
    if (chunkOverlap !== undefined) params.chunk_overlap = chunkOverlap;

    const response = await apiClient.post('/ingest/file', formData, {
      params,
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  // 获取知识库统计
  async getStats(): Promise<KnowledgeBaseStats> {
    const response = await apiClient.get('/knowledge-base/stats');
    const data = response.data;
    return data?.total_files !== undefined ? data : data?.data;
  },

  // 获取文档列表，统一使用统计接口返回的文件快照
  async getFiles(): Promise<KnowledgeBaseStats['files']> {
    const stats = await this.getStats();
    return stats.files || [];
  },

  // 删除文档
  async deleteFile(fileId: string): Promise<void> {
    await apiClient.delete(`/knowledge-base/${fileId}`);
  },

  // ===== 会话管理 =====

  // 获取会话列表
  async getSessions(userDept: string, limit: number = 50): Promise<any> {
    const response = await apiClient.get('/sessions', {
      params: { user_dept: userDept, limit },
    });
    return response.data;
  },

  // 创建新会话
  async createSession(userDept: string, title: string = '新对话'): Promise<any> {
    const response = await apiClient.post('/sessions', null, {
      params: { user_dept: userDept, title },
    });
    return response.data;
  },

  // 获取会话详情（包含消息）
  async getSession(sessionId: string): Promise<any> {
    const response = await apiClient.get(`/sessions/${sessionId}`);
    return response.data;
  },

  // 更新会话标题
  async updateSession(sessionId: string, title: string): Promise<any> {
    const response = await apiClient.put(`/sessions/${sessionId}`, null, {
      params: { title },
    });
    return response.data;
  },

  // 删除会话
  async deleteSession(sessionId: string): Promise<any> {
    const response = await apiClient.delete(`/sessions/${sessionId}`);
    return response.data;
  },

  // 扫描版 PDF：某页的渲染图地址（直接给 <img src> 用）
  pdfPageUrl(fileId: string, pageNo: number): string {
    return `/api/pdf-page/${fileId}/${pageNo}`;
  },

  // 扫描版 PDF：该文件的每页尺寸与每行 bbox（用于画高亮框）
  async getPdfOcrMeta(fileId: string): Promise<PdfOcrMeta> {
    const response = await apiClient.get<PdfOcrMeta>(`/pdf-page/${fileId}/meta`);
    return response.data;
  },
};

export default api;

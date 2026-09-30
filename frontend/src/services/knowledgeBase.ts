import axios, { AxiosInstance } from 'axios';

const API_BASE_URL = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000/api';

class KnowledgeBaseAPI {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      timeout: 30000,
    });
  }

  // 上传文件
  async uploadFile(
    file: File,
    chunkStrategy: string = 'markdown',
    chunkSize: number = 512,
    chunkOverlap: number = 50
  ) {
    const formData = new FormData();
    formData.append('file', file);

    return this.client.post('/ingest/file', formData, {
      params: {
        chunk_strategy: chunkStrategy,
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
      },
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  }

  // 获取知识库统计
  async getStats() {
    return this.client.get('/knowledge-base/stats');
  }

  // 获取文件列表
  async getFileList() {
    return this.client.get('/knowledge-base');
  }

  // 删除文件
  async deleteFile(fileId: string) {
    return this.client.delete(`/knowledge-base/${fileId}`);
  }

  // 搜索
  async search(
    query: string,
    topK: number = 5,
    enableIntent: boolean = true,
    userDept?: string
  ) {
    return this.client.post('/search', null, {
      params: {
        query,
        top_k: topK,
        enable_intent: enableIntent,
        user_dept: userDept,
      },
    });
  }

  // 问答
  async qa(
    query: string,
    topK: number = 3,
    enableIntent: boolean = true,
    userDept?: string,
    sessionId?: string
  ) {
    return this.client.post('/qa', null, {
      params: {
        query,
        top_k: topK,
        enable_intent: enableIntent,
        user_dept: userDept,
        session_id: sessionId,
      },
    });
  }

  // 流式问答
  async qaStream(
    query: string,
    enableIntent: boolean = true,
    userDept?: string,
    sessionId?: string
  ): Promise<EventSource> {
    const params = new URLSearchParams({
      question: query,
      enable_intent: enableIntent.toString(),
      user_dept: userDept || '',
      session_id: sessionId || '',
    });

    return new EventSource(`${API_BASE_URL}/qa/stream?${params}`);
  }
}

const kbAPI = new KnowledgeBaseAPI();
export default kbAPI;

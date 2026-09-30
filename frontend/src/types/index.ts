// 类型定义
export interface AnswerDiagnostics {
  request_id?: string;
  model?: string;
  finish_reason?: string;
  answer_chars?: number;
  reasoning_chars?: number;
  refusal_chars?: number;
  usage?: Record<string, number>;
  error_type?: string;
  fallback_reason?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  sources?: DocumentSource[];
  images?: ImageInfo[];
  fallback?: boolean;
  diagnostics?: AnswerDiagnostics | null;
  isThinking?: boolean;  // 是否正在思考中
  thinkingSteps?: string[];  // 思考步骤
}

export interface ImageInfo {
  url: string;
  description?: string;
  id?: string;
  section?: string;
  path?: string;
  file?: string;
  seq?: string;
}

export interface DocumentSource {
  rank: number;
  text: string;
  score: number;
  filename: string;
  images?: ImageInfo[];
  metadata: {
    source: string;
    owner_dept: string;
    doc_type: string;
    // 扫描版 PDF 才有：定位到具体哪一页
    page_no?: number;
    page_dpi?: number;
    page_width?: number;
    page_height?: number;
    file_id?: string;
    is_scanned?: boolean;
  };
}

/** OCR 识别出的一行文字及其在页面图上的像素坐标 */
export interface OcrLine {
  /** [x0, y0, x1, y1]，渲染原图坐标系下的像素值 */
  bbox: [number, number, number, number];
  confidence: number;
  /** 后端 /meta 会剥掉 text 省带宽，所以这里是可选的 */
  text?: string;
}

export interface OcrPage {
  page_no: number;
  width: number;
  height: number;
  dpi: number;
  lines: OcrLine[];
}

/** GET /api/pdf-page/{file_id}/meta 的返回 */
export interface PdfOcrMeta {
  status: string;
  file_id: string;
  total_pages: number;
  dpi: number;
  pages: Record<string, OcrPage>;
}

export interface ChatResponse {
  status: string;
  answer: string;
  sources: DocumentSource[];
  images: ImageInfo[];
  query: string;
  fallback?: boolean;
  diagnostics?: AnswerDiagnostics | null;
}

export interface SearchResponse {
  status: string;
  results: DocumentSource[];
  query: string;
  total: number;
}

export interface IngestionResponse {
  status: string;
  filename: string;
  chunks: number;
  images: number;
  file_id?: string | null;
  parser_type: string;
  chunk_strategy: string;
  chunk_strategy_version?: string;
  chunk_size?: number;
  chunk_overlap?: number;
  hospitals?: string[];
  analysis?: Record<string, unknown>;
  source_type?: string;
  is_scanned?: boolean | null;
  page_count?: number | null;
  ocr_seconds?: number | null;
  hospital_name?: string | null;
  message: string;
}

export interface UserProfile {
  department: string;
  name?: string;
}

export interface KnowledgeBaseFile {
  id: string;
  filename: string;
  chunks: number;
  images: number;
  hospital?: string | null;
  source_type?: string;
  chunk_strategy?: string;
  chunk_strategy_version?: string | null;
  chunk_size?: number | null;
  chunk_overlap?: number | null;
  file_size?: number;
  created_at?: string | null;
  status?: string;
}

export interface KnowledgeBaseStats {
  status?: string;
  total_files: number;
  total_chunks: number;
  total_images: number;
  total_size_mb: number;
  avg_chunks_per_file?: number;
  avg_images_per_file?: number;
  avg_file_size_kb?: number;
  files: KnowledgeBaseFile[];
}

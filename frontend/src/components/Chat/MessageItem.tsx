import React from 'react';
import { Button, Card, Avatar, Typography, Space, Image, Tag, Collapse, Modal } from 'antd';
import { UserOutlined, RobotOutlined, ThunderboltOutlined, FileImageOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { TypewriterText } from './TypewriterText';
import { MarkdownImage, normalizeImageUrl } from './MarkdownImage';
import PdfPageViewer from './PdfPageViewer';
import type { DocumentSource, Message } from '../../types';

const { Text } = Typography;

interface MessageItemProps {
  message: Message;
  enableTypewriter?: boolean; // 是否启用打字机效果
}

export const MessageItem: React.FC<MessageItemProps> = ({ message, enableTypewriter = true }) => {
  const isUser = message.role === 'user';
  // 扫描版 PDF 命中页：点击「查看原页」时打开
  const [pdfPreview, setPdfPreview] = React.useState<DocumentSource | null>(null);

  const isScannedPdf = (source: DocumentSource) =>
    Boolean(source.metadata?.is_scanned && source.metadata?.file_id && source.metadata?.page_no);

  // 调试：检查是否收到了图片
  React.useEffect(() => {
    if (message.images && message.images.length > 0) {
      console.log('MessageItem received images:', message.images);
    }
  }, [message.images]);

  const normalizedContent = React.useMemo(
    () => message.content.replace(/!!(?=\[[^\]]*\]\([^)]*\))/g, '!'),
    [message.content]
  );
  const hasInlineImages = /!\[[^\]]*\]\([^)]*\)/.test(normalizedContent);

  const formatTime = (timestamp: Date) => {
    const date = new Date(timestamp);
    const today = new Date();
    const isToday = date.toDateString() === today.toDateString();

    const timeStr = date.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit'
    });

    if (isToday) {
      return timeStr;
    }

    const dateStr = date.toLocaleDateString('zh-CN', {
      month: '2-digit',
      day: '2-digit'
    });

    return `${dateStr} ${timeStr}`;
  };

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 16,
      }}
    >
      <div style={{ maxWidth: '70%', display: 'flex', gap: 12 }}>
        {!isUser && (
          <Avatar
            icon={<RobotOutlined />}
            style={{ background: '#1890ff', flexShrink: 0 }}
          />
        )}

        <div style={{ flex: 1 }}>
          <Card
            size="small"
            style={{
              background: isUser ? '#1890ff' : '#fff',
              color: isUser ? '#fff' : '#000',
              borderRadius: 8,
            }}
            bodyStyle={{ padding: '12px 16px' }}
          >
            {/* fallback 提示 */}
            {!isUser && message.fallback && (
              <div
                style={{
                  marginBottom: 10,
                  padding: '8px 10px',
                  border: '1px solid #ffd591',
                  borderRadius: 4,
                  background: '#fff7e6',
                  color: '#ad6800',
                  fontSize: 12,
                }}
              >
                原文资料，非生成答案。模型未能完成总结，以下内容来自本次检索结果。
              </div>
            )}

            {/* 生成诊断 */}
            {!isUser && message.fallback && message.diagnostics && (
              <Collapse
                ghost
                size="small"
                style={{ marginBottom: 10 }}
                items={[{
                  key: 'diagnostics',
                  label: <Text type="secondary" style={{ fontSize: 12 }}>生成诊断</Text>,
                  children: (
                    <div style={{ fontSize: 12, color: '#666', lineHeight: 1.8 }}>
                      {message.diagnostics.fallback_reason && (
                        <div>原因：{message.diagnostics.fallback_reason}</div>
                      )}
                      {message.diagnostics.finish_reason && (
                        <div>结束原因：{message.diagnostics.finish_reason}</div>
                      )}
                      {message.diagnostics.model && (
                        <div>模型：{message.diagnostics.model}</div>
                      )}
                      {message.diagnostics.answer_chars !== undefined && (
                        <div>正文字符数：{message.diagnostics.answer_chars}</div>
                      )}
                      {message.diagnostics.reasoning_chars !== undefined && (
                        <div>推理字符数：{message.diagnostics.reasoning_chars}</div>
                      )}
                      {message.diagnostics.error_type && (
                        <div>错误类型：{message.diagnostics.error_type}</div>
                      )}
                      {message.diagnostics.request_id && (
                        <div>请求 ID：{message.diagnostics.request_id}</div>
                      )}
                      {message.diagnostics.usage && (
                        <div>
                          Token：{message.diagnostics.usage.total_tokens ?? '-'}
                          {' '}（输入 {message.diagnostics.usage.prompt_tokens ?? '-'}，输出 {message.diagnostics.usage.completion_tokens ?? '-'}）
                        </div>
                      )}
                    </div>
                  ),
                }]}
              />
            )}

            {/* 消息内容 */}
            {isUser ? (
              <Text style={{ color: '#fff' }}>{message.content}</Text>
            ) : (
              <>
                {/* 思考过程（仅在有思考步骤且不在思考中时显示折叠） */}
                {!message.isThinking && message.thinkingSteps && message.thinkingSteps.length > 0 && (
                  <Collapse
                    ghost
                    size="small"
                    style={{ marginBottom: 12 }}
                    items={[
                      {
                        key: 'thinking',
                        label: (
                          <Space>
                            <ThunderboltOutlined style={{ color: '#1890ff' }} />
                            <Text type="secondary" style={{ fontSize: 13 }}>
                              思考过程
                            </Text>
                          </Space>
                        ),
                        children: (
                          <div style={{ paddingLeft: 8 }}>
                            {message.thinkingSteps.map((step, idx) => (
                              <div
                                key={idx}
                                style={{
                                  padding: '4px 0',
                                  fontSize: 12,
                                  color: '#666',
                                  display: 'flex',
                                  gap: 8,
                                }}
                              >
                                <span style={{ color: '#1890ff' }}>•</span>
                                <span>{step}</span>
                              </div>
                            ))}
                          </div>
                        ),
                      },
                    ]}
                  />
                )}

                {/* AI 回复内容 */}
                {message.isThinking ? (
                  // 正在思考中，显示思考步骤（打字机效果）
                  <div style={{ color: '#666', fontSize: 13 }}>
                    {message.content.split('\n').map((line, idx) => (
                      <div key={idx} style={{ padding: '2px 0', display: 'flex', gap: 8 }}>
                        <ThunderboltOutlined style={{ color: '#1890ff', marginTop: 2 }} />
                        <span>{line}</span>
                      </div>
                    ))}
                  </div>
                ) : enableTypewriter && !message.sources && !message.images ? (
                  <TypewriterText text={message.content} speed={20} />
                ) : (
                  <div className="markdown-content">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        img: ({ src, alt }) => <MarkdownImage src={src} alt={alt} />,
                      }}
                    >
                      {normalizedContent}
                    </ReactMarkdown>
                  </div>
                )}
              </>
            )}

            {/* 图片展示：仅当答案文本里有内联图片引用时才展示 */}
            {message.images && message.images.length > 0 && hasInlineImages && (
              <div style={{ marginTop: 12 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
                  {message.images.map((img, idx) => (
                    <div key={idx} style={{ textAlign: 'center' }}>
                      <div style={{
                        marginBottom: 8,
                        border: '1px solid #f0f0f0',
                        borderRadius: 4,
                        overflow: 'hidden',
                        background: '#fafafa',
                        cursor: 'pointer'
                      }}>
                        <Image
                          src={normalizeImageUrl(img.url)}
                          alt={img.description || '图片'}
                          style={{ width: '100%', height: 160, objectFit: 'cover' }}
                          preview={true}
                        />
                      </div>
                      {/* 图片描述和章节 */}
                      <div style={{ fontSize: 12, color: '#666', lineHeight: 1.5 }}>
                        {img.description && (
                          <div style={{ fontWeight: 'bold', marginBottom: 4, color: '#333' }}>
                            {img.description}
                          </div>
                        )}
                        {img.section && (
                          <div style={{ fontSize: 11, color: '#999', lineHeight: 1.4, maxHeight: 60, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            📍 {img.section}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 来源文档 */}
            {message.sources && message.sources.length > 0 && (
              <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid #f0f0f0' }}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                  📚 来源文档：
                </Text>
                <Space direction="vertical" size={4}>
                  {message.sources.slice(0, 3).map((source, idx) => (
                    <div key={idx} style={{ fontSize: 12 }}>
                      <Tag color="blue" style={{ marginRight: 4 }}>
                        {source.metadata.doc_type}
                      </Tag>
                      <Text type="secondary">{source.metadata.source}</Text>
                      {isScannedPdf(source) && (
                        <>
                          <Tag color="purple" style={{ marginLeft: 4 }}>
                            第 {source.metadata.page_no} 页
                          </Tag>
                          <Button
                            type="link"
                            size="small"
                            icon={<FileImageOutlined />}
                            style={{ paddingLeft: 4 }}
                            onClick={() => setPdfPreview(source)}
                          >
                            查看原页
                          </Button>
                        </>
                      )}
                    </div>
                  ))}
                </Space>
              </div>
            )}
          </Card>

          {/* 时间戳 */}
          <Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
            {formatTime(message.timestamp)}
          </Text>
        </div>

        {isUser && (
          <Avatar
            icon={<UserOutlined />}
            style={{ background: '#52c41a', flexShrink: 0 }}
          />
        )}
      </div>

      <Modal
        open={Boolean(pdfPreview)}
        title={
          pdfPreview ? `${pdfPreview.filename} · 第 ${pdfPreview.metadata.page_no} 页` : ''
        }
        footer={null}
        width={860}
        onCancel={() => setPdfPreview(null)}
        destroyOnClose
      >
        {pdfPreview?.metadata?.file_id && (
          <PdfPageViewer
            fileId={pdfPreview.metadata.file_id}
            pageNo={Number(pdfPreview.metadata.page_no)}
            highlightText={pdfPreview.text}
          />
        )}
      </Modal>
    </div>
  );
};

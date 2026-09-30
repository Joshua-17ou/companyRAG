import React, { useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Input,
  InputNumber,
  List,
  Modal,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
  message,
  Empty,
  Divider,
} from 'antd';
import { SearchOutlined, RobotOutlined, FileImageOutlined } from '@ant-design/icons';
import kbAPI from '../services/knowledgeBase';
import PdfPageViewer from '../components/Chat/PdfPageViewer';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

interface SearchResult {
  rank: number;
  text: string;
  score: number;
  filename: string;
  hospital?: string;
  images?: any[];
  metadata?: any;
}

interface QAResult {
  answer: string;
  sources: SearchResult[];
  images?: any[];
}

export const SearchPage: React.FC = () => {
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(5);
  const [enableIntent, setEnableIntent] = useState(true);
  const [loadingSearch, setLoadingSearch] = useState(false);
  const [searchResult, setSearchResult] = useState<any>(null);
  const [qaResult, setQaResult] = useState<QAResult | null>(null);
  const [qaLoading, setQaLoading] = useState(false);
  const [qaAnswer, setQaAnswer] = useState('');
  // 扫描版 PDF 命中页：点击「查看原页」时打开
  const [pdfPreview, setPdfPreview] = useState<SearchResult | null>(null);

  const handleSearch = async () => {
    if (!query.trim()) {
      message.warning('请输入搜索内容');
      return;
    }

    setLoadingSearch(true);
    try {
      const response = await kbAPI.search(query, topK, enableIntent);
      setSearchResult(response.data);
      setQaResult(null);
    } catch (error: any) {
      message.error(error.response?.data?.detail || '搜索失败');
    } finally {
      setLoadingSearch(false);
    }
  };

  const handleQA = async () => {
    if (!query.trim()) {
      message.warning('请输入问题');
      return;
    }

    setQaLoading(true);
    setQaAnswer('');
    setQaResult(null);

    try {
      const response = await kbAPI.qa(query, 3, enableIntent);
      setQaResult(response.data);
      setQaAnswer(response.data.answer || '');
    } catch (error: any) {
      message.error(error.response?.data?.detail || '问答失败');
    } finally {
      setQaLoading(false);
    }
  };

  const isScannedPdf = (item: SearchResult) =>
    Boolean(item.metadata?.is_scanned && item.metadata?.file_id && item.metadata?.page_no);

  const renderSearchResult = (item: SearchResult) => (
    <List.Item>
      <List.Item.Meta
        avatar={<Tag color="blue">#{item.rank}</Tag>}
        title={
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space>
              <Text strong>{item.filename}</Text>
              {item.hospital && <Tag color="green">{item.hospital}</Tag>}
              {isScannedPdf(item) && (
                <Tag color="purple">第 {item.metadata.page_no} 页</Tag>
              )}
              <Text type="secondary" style={{ fontSize: 12 }}>
                相似度 {Number(item.score || 0).toFixed(3)}
              </Text>
            </Space>
          </Space>
        }
        description={
          <>
            <Paragraph
              ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
              style={{ marginBottom: 0 }}
            >
              {item.text}
            </Paragraph>
            {isScannedPdf(item) && (
              <Button
                type="link"
                size="small"
                icon={<FileImageOutlined />}
                style={{ paddingLeft: 0 }}
                onClick={() => setPdfPreview(item)}
              >
                查看原页
              </Button>
            )}
          </>
        }
      />
    </List.Item>
  );

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* 查询输入区 */}
        <Card>
          <Space direction="vertical" style={{ width: '100%' }}>
            <TextArea
              placeholder="输入搜索查询或问题..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  handleSearch();
                }
              }}
              rows={3}
              allowClear
            />

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Space>
                <Text>启用意图识别</Text>
                <Switch checked={enableIntent} onChange={setEnableIntent} />
                <InputNumber
                  min={1}
                  max={20}
                  value={topK}
                  onChange={(value) => setTopK(value || 5)}
                  addonBefore="Top K"
                  style={{ width: 120 }}
                />
              </Space>

              <Space>
                <Button
                  type="primary"
                  icon={<SearchOutlined />}
                  onClick={handleSearch}
                  loading={loadingSearch}
                >
                  搜索
                </Button>
                <Button
                  icon={<RobotOutlined />}
                  onClick={handleQA}
                  loading={qaLoading}
                >
                  问答
                </Button>
              </Space>
            </div>
          </Space>
        </Card>

        {/* 权限提示 */}
        <Alert
          type="info"
          showIcon
          message="权限说明"
          description="搜索结果已根据您的部门权限进行过滤。如需访问更多内容，请联系管理员。"
          closable
        />

        {/* 搜索结果 */}
        {loadingSearch && <Spin style={{ display: 'block', margin: 32 }} />}

        {searchResult && !loadingSearch && (
          <Card
            title={`搜索结果 (${searchResult.count ?? 0} 条)`}
          >
            {searchResult.results && searchResult.results.length > 0 ? (
              <List
                dataSource={searchResult.results}
                renderItem={(item: SearchResult) =>
                  renderSearchResult(item)
                }
                locale={{ emptyText: '无搜索结果' }}
              />
            ) : (
              <Empty description="未找到相关文档" />
            )}
          </Card>
        )}

        {/* 问答结果 */}
        {(qaLoading || qaResult || qaAnswer) && (
          <Card title="问答结果">
            {qaLoading && (
              <Spin tip="AI 正在思考..." />
            )}

            {qaAnswer && (
              <>
                <div
                  style={{
                    background: '#f5f5f5',
                    padding: 16,
                    borderRadius: 4,
                    marginBottom: 16,
                    minHeight: 60,
                    maxHeight: 300,
                    overflowY: 'auto',
                    fontFamily: 'monospace',
                    fontSize: 13,
                    lineHeight: 1.6,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {qaAnswer}
                </div>

                {qaResult?.sources && qaResult.sources.length > 0 && (
                  <>
                    <Divider orientation="left">引用来源</Divider>
                    <List
                      size="small"
                      dataSource={qaResult.sources.slice(0, 3)}
                      renderItem={(source: SearchResult) => (
                        <List.Item>
                          <List.Item.Meta
                            title={
                              <Space>
                                <Text strong>{source.filename}</Text>
                                {source.hospital && (
                                  <Tag color="green">{source.hospital}</Tag>
                                )}
                              </Space>
                            }
                            description={
                              <Paragraph
                                ellipsis={{ rows: 2, expandable: true }}
                                style={{ marginBottom: 0 }}
                              >
                                {source.text}
                              </Paragraph>
                            }
                          />
                        </List.Item>
                      )}
                    />
                  </>
                )}

                {qaResult?.images && qaResult.images.length > 0 && (
                  <>
                    <Divider orientation="left">相关图片</Divider>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 16 }}>
                      {qaResult.images.map((img, idx) => (
                        <div key={idx} style={{ textAlign: 'center' }}>
                          <img
                            src={img.path || img.url}
                            alt={img.description}
                            style={{ maxWidth: '100%', maxHeight: 200, borderRadius: 4 }}
                          />
                          {img.description && (
                            <Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: 'block' }}>
                              {img.description}
                            </Text>
                          )}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </>
            )}
          </Card>
        )}
      </Space>

      <Modal
        open={Boolean(pdfPreview)}
        title={pdfPreview ? `${pdfPreview.filename} · 第 ${pdfPreview.metadata.page_no} 页` : ''}
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

import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Col, Form, InputNumber, Row, Select, Space, Statistic, Table, Tag, Upload, message, Modal, Progress, Tooltip } from 'antd';
import { UploadOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons';
import kbAPI from '../services/knowledgeBase';

type Stats = {
  total_files: number;
  total_chunks: number;
  total_images: number;
  total_size_mb: number;
  avg_chunks_per_file: number;
  files: Array<{
    id: string;
    filename: string;
    chunks: number;
    images: number;
    hospital?: string;
    chunk_strategy?: string;
    created_at?: string;
  }>;
};

export const KnowledgeBasePage: React.FC = () => {
  const [stats, setStats] = useState<Stats | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [result, setResult] = useState<any>(null);
  const [strategy, setStrategy] = useState('auto');
  const [chunkSize, setChunkSize] = useState(512);
  const [chunkOverlap, setChunkOverlap] = useState(50);
  const [deleteConfirmVisible, setDeleteConfirmVisible] = useState(false);
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadStats = useCallback(async () => {
    try {
      const response = await kbAPI.getStats();
      setStats(response.data as Stats);
    } catch (error: any) {
      message.error(error.message || '加载知识库失败');
    }
  }, []);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  const uploadProps = {
    showUploadList: false,
    accept: '.md,.markdown,.txt,.pdf',
    beforeUpload: async (file: File) => {
      if (chunkOverlap >= chunkSize) {
        message.error('Chunk overlap 必须小于 Chunk size');
        return Upload.LIST_IGNORE;
      }

      setUploading(true);
      setUploadProgress(0);

      try {
        // 模拟进度
        const progressInterval = setInterval(() => {
          setUploadProgress((prev) => {
            if (prev < 90) {
              return prev + Math.random() * 20;
            }
            return prev;
          });
        }, 300);

        const response = await kbAPI.uploadFile(file, strategy, chunkSize, chunkOverlap);

        clearInterval(progressInterval);
        setUploadProgress(100);

        const uploadResult = response.data;
        setResult(uploadResult);
        message.success(`✓ 文档入库成功：${uploadResult.chunks} 个chunks`);

        // 延迟刷新统计
        setTimeout(() => {
          loadStats();
          setUploadProgress(0);
        }, 500);
      } catch (error: any) {
        message.error(error.response?.data?.detail || error.message || '文档上传失败');
      } finally {
        setUploading(false);
      }

      return Upload.LIST_IGNORE;
    },
  };

  const handleDelete = async () => {
    if (!deleteTargetId) return;

    setDeleting(true);
    try {
      await kbAPI.deleteFile(deleteTargetId);
      message.success('文档已删除');
      setDeleteConfirmVisible(false);
      setDeleteTargetId(null);
      await loadStats();
    } catch (error: any) {
      message.error(error.message || '删除失败');
    } finally {
      setDeleting(false);
    }
  };

  const columns = [
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      ellipsis: true,
      render: (text: string) => <Tooltip title={text}>{text}</Tooltip>,
    },
    {
      title: 'Chunks',
      dataIndex: 'chunks',
      key: 'chunks',
      width: 80,
      render: (text: number) => <Tag color="blue">{text}</Tag>,
    },
    {
      title: '图片',
      dataIndex: 'images',
      key: 'images',
      width: 80,
      render: (text: number) => <Tag color="cyan">{text}</Tag>,
    },
    {
      title: '医院',
      dataIndex: 'hospital',
      key: 'hospital',
      width: 100,
      render: (value: string) => value ? <Tag color="green">{value}</Tag> : <span>-</span>,
    },
    {
      title: '策略',
      dataIndex: 'chunk_strategy',
      key: 'chunk_strategy',
      width: 120,
      render: (value: string) => <Tag>{value || 'character'}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (text: string) => text ? new Date(text).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, record: any) => (
        <Button
          danger
          size="small"
          icon={<DeleteOutlined />}
          onClick={() => {
            setDeleteTargetId(record.id);
            setDeleteConfirmVisible(true);
          }}
        >
          删除
        </Button>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* 知识库概览 */}
        <Card
          title="知识库概览"
          extra={
            <Button
              icon={<ReloadOutlined />}
              onClick={loadStats}
              loading={!stats}
            >
              刷新
            </Button>
          }
        >
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="文件数" value={stats?.total_files || 0} />
            </Col>
            <Col span={6}>
              <Statistic title="Chunks" value={stats?.total_chunks || 0} />
            </Col>
            <Col span={6}>
              <Statistic title="图片数" value={stats?.total_images || 0} />
            </Col>
            <Col span={6}>
              <Statistic
                title="大小（MB）"
                value={stats?.total_size_mb || 0}
                precision={2}
              />
            </Col>
          </Row>
          {stats?.avg_chunks_per_file && (
            <div style={{ marginTop: 16, color: '#666', fontSize: 12 }}>
              平均每个文件: {stats.avg_chunks_per_file.toFixed(1)} chunks
            </div>
          )}
        </Card>

        {/* 上传文档 */}
        <Card title="上传文档">
          <Form layout="vertical">
            <Row gutter={16}>
              <Col span={6}>
                <Form.Item label="切分策略" style={{ marginBottom: 0 }}>
                  <Select
                    value={strategy}
                    onChange={setStrategy}
                    options={[
                      { value: 'auto', label: '自动识别' },
                      { value: 'markdown', label: 'Markdown' },
                      { value: 'hospital_markdown', label: '医院指南' },
                      { value: 'character', label: '普通文本' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item label="Chunk 大小" style={{ marginBottom: 0 }}>
                  <InputNumber
                    min={1}
                    value={chunkSize}
                    onChange={(value) => setChunkSize(value || 512)}
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item label="重叠" style={{ marginBottom: 0 }}>
                  <InputNumber
                    min={0}
                    value={chunkOverlap}
                    onChange={(value) => setChunkOverlap(value || 0)}
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>
              <Col span={6} style={{ display: 'flex', alignItems: 'flex-end' }}>
                <Upload {...uploadProps} style={{ width: '100%' }}>
                  <Button
                    type="primary"
                    icon={<UploadOutlined />}
                    loading={uploading}
                    style={{ width: '100%' }}
                  >
                    选择并上传
                  </Button>
                </Upload>
              </Col>
            </Row>

            {/* 上传进度 */}
            {uploading && uploadProgress > 0 && (
              <div style={{ marginTop: 16 }}>
                <Progress
                  percent={Math.min(uploadProgress, 100)}
                  status={uploadProgress >= 100 ? 'success' : 'active'}
                />
              </div>
            )}

            {/* 上传结果 */}
            {result && !uploading && (
              <Alert
                style={{ marginTop: 16 }}
                type="success"
                message={`已使用 ${result.chunk_strategy}，生成 ${result.chunks} 个 chunks`}
                description={`识别医院：${result.hospitals?.join('、') || '无'}；图片：${result.images}`}
                showIcon
                closable
                onClose={() => setResult(null)}
              />
            )}
          </Form>
        </Card>

        {/* 文档列表 */}
        <Card title={`文档列表 (${stats?.files?.length || 0})`}>
          {stats?.files && stats.files.length > 0 ? (
            <Table
              rowKey="id"
              columns={columns}
              dataSource={stats.files}
              pagination={{
                pageSize: 10,
                total: stats.files.length,
                showSizeChanger: true,
                showTotal: (total) => `共 ${total} 个文件`,
              }}
              size="small"
              scroll={{ x: 1200 }}
            />
          ) : (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
              暂无文档，请上传文档开始使用
            </div>
          )}
        </Card>
      </Space>

      {/* 删除确认对话框 */}
      <Modal
        title="确认删除"
        open={deleteConfirmVisible}
        onOk={handleDelete}
        onCancel={() => {
          setDeleteConfirmVisible(false);
          setDeleteTargetId(null);
        }}
        okButtonProps={{ loading: deleting, danger: true }}
        okText="删除"
        cancelText="取消"
      >
        <p>确定要删除这个文档吗？删除后将无法恢复。</p>
      </Modal>
    </div>
  );
};

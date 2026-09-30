import React, { useState } from 'react';
import { List, Button, Popconfirm, Empty, Typography, Input } from 'antd';
import { PlusOutlined, DeleteOutlined, MessageOutlined, EditOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

interface SessionListProps {
  sessions: Session[];
  currentSessionId: string | null;
  onCreateSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onRenameSession: (sessionId: string, newTitle: string) => void;
}

export const SessionList: React.FC<SessionListProps> = ({
  sessions,
  currentSessionId,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
  onRenameSession,
}) => {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return '刚刚';
    if (diffMins < 60) return `${diffMins}分钟前`;

    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}小时前`;

    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}天前`;

    return date.toLocaleDateString('zh-CN');
  };

  const handleStartEdit = (session: Session, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(session.id);
    setEditingTitle(session.title);
  };

  const handleSaveEdit = (sessionId: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (editingTitle.trim() && editingTitle !== sessions.find(s => s.id === sessionId)?.title) {
      onRenameSession(sessionId, editingTitle.trim());
    }
    setEditingId(null);
    setEditingTitle('');
  };

  const handleCancelEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(null);
    setEditingTitle('');
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 新建会话按钮 */}
      <div style={{ padding: '12px' }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={onCreateSession}
          block
          size="large"
        >
          新建对话
        </Button>
      </div>

      {/* 会话列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 12px' }}>
        {sessions.length === 0 ? (
          <Empty
            description="暂无对话"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ marginTop: '40px' }}
          />
        ) : (
          <List
            dataSource={sessions}
            renderItem={(session) => (
              <List.Item
                key={session.id}
                style={{
                  padding: '12px',
                  marginBottom: '8px',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  background: currentSessionId === session.id ? '#e6f4ff' : '#fafafa',
                  border: currentSessionId === session.id ? '1px solid #91caff' : '1px solid #f0f0f0',
                  transition: 'all 0.2s',
                }}
                onClick={() => editingId !== session.id && onSelectSession(session.id)}
                onMouseEnter={(e) => {
                  if (currentSessionId !== session.id) {
                    e.currentTarget.style.background = '#f5f5f5';
                  }
                }}
                onMouseLeave={(e) => {
                  if (currentSessionId !== session.id) {
                    e.currentTarget.style.background = '#fafafa';
                  }
                }}
              >
                <div style={{ width: '100%' }}>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'flex-start',
                    }}
                  >
                    <div style={{ flex: 1, overflow: 'hidden' }}>
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          marginBottom: '4px',
                        }}
                      >
                        <MessageOutlined style={{ marginRight: '6px', color: '#1890ff', flexShrink: 0 }} />

                        {editingId === session.id ? (
                          <div style={{ display: 'flex', gap: '4px', flex: 1 }} onClick={(e) => e.stopPropagation()}>
                            <Input
                              value={editingTitle}
                              onChange={(e) => setEditingTitle(e.target.value)}
                              onPressEnter={(e) => handleSaveEdit(session.id, e as any)}
                              size="small"
                              style={{ flex: 1 }}
                              autoFocus
                            />
                            <CheckOutlined
                              style={{ color: '#52c41a', fontSize: '16px', cursor: 'pointer' }}
                              onClick={(e) => handleSaveEdit(session.id, e)}
                            />
                            <CloseOutlined
                              style={{ color: '#ff4d4f', fontSize: '16px', cursor: 'pointer' }}
                              onClick={handleCancelEdit}
                            />
                          </div>
                        ) : (
                          <Text
                            strong
                            ellipsis
                            style={{
                              fontSize: '14px',
                              maxWidth: '140px',
                            }}
                          >
                            {session.title}
                          </Text>
                        )}
                      </div>
                      <Text type="secondary" style={{ fontSize: '12px' }}>
                        {formatDate(session.updated_at)}
                      </Text>
                    </div>

                    {editingId !== session.id && (
                      <div style={{ display: 'flex', gap: '4px', marginLeft: '8px' }}>
                        <EditOutlined
                          style={{
                            fontSize: '16px',
                            color: '#999',
                            padding: '4px',
                          }}
                          onClick={(e) => handleStartEdit(session, e)}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.color = '#1890ff';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.color = '#999';
                          }}
                        />
                        <Popconfirm
                          title="确认删除"
                          description="删除后无法恢复，确认删除此对话？"
                          onConfirm={(e) => {
                            e?.stopPropagation();
                            onDeleteSession(session.id);
                          }}
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true }}
                        >
                          <DeleteOutlined
                            style={{
                              fontSize: '16px',
                              color: '#999',
                              padding: '4px',
                            }}
                            onClick={(e) => e.stopPropagation()}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.color = '#ff4d4f';
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.color = '#999';
                            }}
                          />
                        </Popconfirm>
                      </div>
                    )}
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
      </div>
    </div>
  );
};

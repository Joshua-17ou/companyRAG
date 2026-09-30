import React, { useEffect, useRef } from 'react';
import { Card, Input, Button, Space, Switch, Empty, Spin, Layout, Avatar, Typography } from 'antd';
import { SendOutlined, DeleteOutlined, ThunderboltOutlined, RobotOutlined } from '@ant-design/icons';
import { MessageItem } from './MessageItem';
import { SessionList } from './SessionList';
import { useChat } from '../../hooks/useChat';
import { useChatStore } from '../../store/chatStore';

const { TextArea } = Input;
const { Sider } = Layout;
const { Text } = Typography;

export const ChatWindow: React.FC = () => {
  const [inputValue, setInputValue] = React.useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const {
    messages,
    isLoading,
    sendMessage,
    enableIntent,
    setEnableIntent,
    sessions,
    currentSessionId,
    createSession,
    switchSession,
    deleteSession,
    renameSession,
  } = useChat();

  const clearMessages = useChatStore((state) => state.clearMessages);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (inputValue.trim() && !isLoading) {
      sendMessage(inputValue);
      setInputValue('');
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <Layout style={{ height: 'calc(100vh - 64px)', background: '#fff', display: 'flex' }}>
      {/* 左侧会话列表 - 固定宽度 */}
      <Sider
        width={280}
        style={{
          background: '#fff',
          borderRight: '1px solid #edf0f5',
          overflow: 'auto',
          flex: '0 0 280px',
          height: '100%',
        }}
      >
        <SessionList
          sessions={sessions}
          currentSessionId={currentSessionId}
          onCreateSession={createSession}
          onSelectSession={switchSession}
          onDeleteSession={deleteSession}
          onRenameSession={renameSession}
        />
      </Sider>

      {/* 右侧对话区域 - 用flex布局重构 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* 工具栏 - 固定高度，不参与滚动 */}
        <div
          style={{
            padding: '12px 16px',
            borderBottom: '1px solid #f0f0f0',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            backgroundColor: '#fff',
            flexShrink: 0,
          }}
        >
          <Space>
            <ThunderboltOutlined />
            <span>意图识别</span>
            <Switch checked={enableIntent} onChange={setEnableIntent} size="small" />
          </Space>

          <Button
            icon={<DeleteOutlined />}
            onClick={clearMessages}
            size="small"
            disabled={messages.length === 0}
          >
            清空对话
          </Button>
        </div>

        {/* 消息列表容器 - 可滚动 */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '16px',
            background: '#fafafa',
          }}
        >
            {messages.length === 0 ? (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Empty
                  description="开始对话吧！我可以帮你查询知识库中的信息"
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              </div>
            ) : (
              <>
                {messages.map((message, index) => (
                  <MessageItem
                    key={message.id}
                    message={message}
                    enableTypewriter={!isLoading && index === messages.length - 1 && message.role === 'assistant'}
                  />
                ))}
                {isLoading && (
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'flex-start',
                      marginBottom: '16px',
                    }}
                  >
                    <div style={{ maxWidth: '70%', display: 'flex', gap: 12 }}>
                      <Avatar
                        icon={<RobotOutlined />}
                        style={{ background: '#1890ff', flexShrink: 0 }}
                      />
                      <div style={{ flex: 1 }}>
                        <Card
                          size="small"
                          style={{
                            background: '#fff',
                            borderRadius: 8,
                          }}
                          bodyStyle={{ padding: '12px 16px' }}
                        >
                          <Space>
                            <Spin size="small" />
                            <Text type="secondary">AI 正在思考中...</Text>
                          </Space>
                        </Card>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </>
            )}
          </div>

        {/* 输入框 - 固定高度，不参与滚动 */}
        <div
          style={{
            padding: '16px',
            borderTop: '1px solid #f0f0f0',
            backgroundColor: '#fff',
            flexShrink: 0,
          }}
        >
          <Space.Compact style={{ width: '100%' }}>
            <TextArea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="请输入您的问题... (Shift+Enter 换行，Enter 发送)"
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={isLoading}
              style={{ flex: 1 }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={isLoading}
              disabled={!inputValue.trim()}
              style={{ height: 'auto' }}
            >
              发送
            </Button>
          </Space.Compact>
        </div>
      </div>
    </Layout>
  );
};

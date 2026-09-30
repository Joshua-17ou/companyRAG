import React from 'react';
import { Layout, Avatar, Dropdown, Space, Typography } from 'antd';
import { LogoutOutlined, UserOutlined } from '@ant-design/icons';
import { GlobalSider } from './GlobalSider';
import type { MenuProps } from 'antd';
import { useChatStore } from '../../store/chatStore';

const { Header, Content } = Layout;
const { Text } = Typography;

interface MainLayoutProps {
  children: React.ReactNode;
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const { userProfile, setUserProfile, clearMessages } = useChatStore();

  const handleLogout = () => {
    setUserProfile(null);
    clearMessages();
  };

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: `${userProfile?.department}部门`,
      disabled: true,
    },
    {
      type: 'divider',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      onClick: handleLogout,
    },
  ];

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <GlobalSider />
      <Layout>
      {/* 顶部导航 */}
      <Header
        style={{
          background: '#fff',
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 1000,
        }}
      >
        <Text strong style={{ fontSize: 16 }}>
          企业知识库助手
        </Text>

        <Space>
          {/* 用户菜单 */}
          <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
            <Space style={{ cursor: 'pointer' }}>
              <Avatar icon={<UserOutlined />} style={{ background: '#667eea' }} />
              <div style={{ lineHeight: '20px' }}>
                <div style={{ fontWeight: 500, fontSize: 14 }}>{userProfile?.department}部门</div>
                <div style={{ fontSize: 12, color: '#999' }}>部门用户</div>
              </div>
            </Space>
          </Dropdown>
        </Space>
      </Header>

      {/* 内容区 */}
      <Content
        style={{
          marginTop: 64,
          background: '#f0f2f5',
        }}
      >
        {children}
      </Content>
      </Layout>
    </Layout>
  );
};

import React from 'react';
import { Layout, Menu } from 'antd';
import { DatabaseOutlined, MessageOutlined, SearchOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';

const { Sider } = Layout;

export const GlobalSider: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <Sider
      width={208}
      theme="light"
      breakpoint="lg"
      collapsedWidth="0"
      className="global-sider"
      style={{ borderRight: '1px solid #e8ecf4', background: '#f8faff' }}
    >
      <div style={{ padding: '22px 20px 14px', fontWeight: 700, color: '#26345d', letterSpacing: 1 }}>知识库助手</div>
      <Menu
        mode="inline"
        className="global-nav-menu"
        selectedKeys={[location.pathname.startsWith('/knowledge-base') ? '/knowledge-base' : location.pathname.startsWith('/search') ? '/search' : '/chat']}
        onClick={({ key }) => navigate(key)}
        items={[
          { key: '/chat', icon: <MessageOutlined />, label: '对话' },
          { key: '/search', icon: <SearchOutlined />, label: '文档搜索' },
          { key: '/knowledge-base', icon: <DatabaseOutlined />, label: '知识库管理' },
        ]}
      />
    </Sider>
  );
};

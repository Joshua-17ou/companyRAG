import React from 'react';
import { ConfigProvider, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { DeptSelector } from './components/Auth/DeptSelector';
import { MainLayout } from './components/Layout/MainLayout';
import { BrowserRouter, Navigate, useLocation } from 'react-router-dom';
import { AppRoutes } from './routes/AppRoutes';
import { useChatStore } from './store/chatStore';
import './styles/global.css';

const RoutedApp: React.FC = () => {
  const userProfile = useChatStore((state) => state.userProfile);
  const location = useLocation();

  if (!userProfile) return <DeptSelector />;
  if (location.pathname === '/') return <Navigate to="/chat" replace />;
  return <MainLayout><AppRoutes /></MainLayout>;
};

const App: React.FC = () => {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#667eea',
          borderRadius: 8,
        },
        algorithm: theme.defaultAlgorithm,
      }}
    >
      <BrowserRouter>
        <RoutedApp />
      </BrowserRouter>
    </ConfigProvider>
  );
};

export default App;

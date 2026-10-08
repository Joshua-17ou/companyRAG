import React, { useEffect, useState } from 'react';
import { ConfigProvider, Spin, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { BrowserRouter, Navigate, useLocation } from 'react-router-dom';
import { MainLayout } from '../components/Layout/MainLayout';
import { AppRoutes } from '../routes/AppRoutes';
import { useChatStore } from '../store/chatStore';
import { AuthCallbackPage } from './AuthCallbackPage';
import { LoginGate } from './LoginGate';
import { authApi } from './auth';
import { LARK_CALLBACK_PATH, VISIBILITY_DEPT } from './config';
import '../styles/global.css';

/**
 * 飞书版应用外壳
 *
 * 复用原网页版的布局与页面（MainLayout / AppRoutes），
 * 只把入口处的「部门选择」换成「飞书免登」。
 */
const LarkGate: React.FC = () => {
  const userProfile = useChatStore((state) => state.userProfile);
  const setUserProfile = useChatStore((state) => state.setUserProfile);
  const [booted, setBooted] = useState(false);
  const location = useLocation();

  useEffect(() => {
    // 可见性部门固定为「全员」，后端会依据登录令牌覆盖为真实归属
    localStorage.setItem('user_dept', VISIBILITY_DEPT);

    let alive = true;
    authApi
      .me()
      .then((user) => {
        if (alive) setUserProfile({ name: user.name, department: VISIBILITY_DEPT });
      })
      .catch(() => {
        // 未登录：交给 LoginGate 走飞书授权
      })
      .finally(() => {
        if (alive) setBooted(true);
      });

    return () => {
      alive = false;
    };
  }, [setUserProfile]);

  // 授权回跳页不经过登录门
  if (location.pathname === LARK_CALLBACK_PATH) return <AuthCallbackPage />;

  if (!booted) {
    return (
      <div
        style={{
          height: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Spin size="large" />
      </div>
    );
  }

  if (!userProfile) return <LoginGate />;
  if (location.pathname === '/') return <Navigate to="/chat" replace />;
  return (
    <MainLayout>
      <AppRoutes />
    </MainLayout>
  );
};

export const FeishuApp: React.FC = () => (
  <ConfigProvider
    locale={zhCN}
    theme={{
      token: { colorPrimary: '#667eea', borderRadius: 8 },
      algorithm: theme.defaultAlgorithm,
    }}
  >
    <BrowserRouter>
      <LarkGate />
    </BrowserRouter>
  </ConfigProvider>
);

export default FeishuApp;
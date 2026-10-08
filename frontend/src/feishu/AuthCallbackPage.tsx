import React, { useEffect, useRef, useState } from 'react';
import { Button, Result, Spin } from 'antd';
import { useNavigate } from 'react-router-dom';
import { authApi } from './auth';
import { VISIBILITY_DEPT } from './config';
import { useChatStore } from '../store/chatStore';

/**
 * 飞书授权回跳页：/auth/callback?code=..&state=..
 * 换取登录态后写入 store 并回到 /chat。
 */
export const AuthCallbackPage: React.FC = () => {
  const navigate = useNavigate();
  const setUserProfile = useChatStore((state) => state.setUserProfile);
  const [error, setError] = useState<string | null>(null);
  const handled = useRef(false); // 授权码一次性，避免 StrictMode 重复兑换

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state') || '';

    if (!code) {
      setError('未收到飞书授权码');
      return;
    }

    authApi
      .exchange(code, state)
      .then((user) => {
        localStorage.setItem('user_dept', VISIBILITY_DEPT);
        setUserProfile({ name: user.name, department: VISIBILITY_DEPT });
        navigate('/chat', { replace: true });
      })
      .catch((e: any) => {
        setError(e?.response?.data?.detail || e?.message || '飞书登录失败');
      });
  }, [navigate, setUserProfile]);

  if (error) {
    return (
      <Result
        status="error"
        title="登录失败"
        subTitle={error}
        extra={
          <Button type="primary" onClick={() => authApi.redirectToFeishu()}>
            重新登录
          </Button>
        }
      />
    );
  }

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
      }}
    >
      <Spin size="large" />
      <span>正在完成飞书登录…</span>
    </div>
  );
};

export default AuthCallbackPage;
import React, { useCallback, useEffect, useState } from 'react';
import { Button, Spin, Typography } from 'antd';
import { authApi } from './auth';

const { Text } = Typography;

/** 免登入口：自动跳转飞书授权页，失败时给出重试 */
export const LoginGate: React.FC = () => {
  const [error, setError] = useState<string | null>(null);
  const [redirecting, setRedirecting] = useState(false);

  const startLogin = useCallback(async () => {
    setError(null);
    setRedirecting(true);
    try {
      await authApi.redirectToFeishu();
    } catch (e: any) {
      setRedirecting(false);
      setError(e?.response?.data?.detail || e?.message || '无法跳转到飞书授权页');
    }
  }, []);

  useEffect(() => {
    startLogin();
  }, [startLogin]);

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        padding: 24,
        textAlign: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      }}
    >
      {error ? (
        <>
          <Text style={{ color: '#fff' }}>{error}</Text>
          <Button type="primary" onClick={startLogin}>
            重新登录
          </Button>
        </>
      ) : (
        <>
          {redirecting && <Spin size="large" />}
          <Text style={{ color: '#fff' }}>正在通过飞书登录…</Text>
        </>
      )}
    </div>
  );
};

export default LoginGate;
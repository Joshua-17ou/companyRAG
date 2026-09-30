import React, { useState } from 'react';
import { Card, Select, Button, Typography, Space } from 'antd';
import { UserOutlined } from '@ant-design/icons';
import { useChatStore } from '../../store/chatStore';

const { Title, Text } = Typography;
const { Option } = Select;

const departments = ['销售', '财务', '行政'];

export const DeptSelector: React.FC = () => {
  const [selectedDept, setSelectedDept] = useState<string>('');
  const setUserProfile = useChatStore((state) => state.setUserProfile);

  const handleLogin = () => {
    if (selectedDept) {
      setUserProfile({ department: selectedDept });
    }
  };

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      }}
    >
      <Card
        style={{
          width: 400,
          boxShadow: '0 8px 32px rgba(0,0,0,0.1)',
          borderRadius: 12,
        }}
      >
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div style={{ textAlign: 'center' }}>
            <UserOutlined style={{ fontSize: 48, color: '#667eea' }} />
            <Title level={3} style={{ marginTop: 16 }}>
              企业知识库
            </Title>
            <Text type="secondary">请选择您的部门登录</Text>
          </div>

          <Select
            size="large"
            placeholder="选择部门"
            style={{ width: '100%' }}
            value={selectedDept}
            onChange={setSelectedDept}
          >
            {departments.map((dept) => (
              <Option key={dept} value={dept}>
                {dept}
              </Option>
            ))}
          </Select>

          <Button
            type="primary"
            size="large"
            block
            onClick={handleLogin}
            disabled={!selectedDept}
          >
            登录
          </Button>
        </Space>
      </Card>
    </div>
  );
};

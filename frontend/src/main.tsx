import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import FeishuApp from './feishu/FeishuApp';
import { FEISHU_ENABLED } from './feishu/config';

// VITE_LARK_ENABLED=true 时启用飞书免登入口，否则走原网页版流程
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {FEISHU_ENABLED ? <FeishuApp /> : <App />}
  </React.StrictMode>
);

import React from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { ChatWindow } from '../components/Chat/ChatWindow';
import { KnowledgeBasePage } from '../pages/KnowledgeBasePage';
import { SearchPage } from '../pages/SearchPage';

export const AppRoutes: React.FC = () => (
  <Routes>
    <Route path="/chat" element={<ChatWindow />} />
    <Route path="/search" element={<SearchPage />} />
    <Route path="/knowledge-base" element={<KnowledgeBasePage />} />
    <Route path="*" element={<Navigate to="/chat" replace />} />
  </Routes>
);

import { useState, useEffect } from 'react';
import { message as antdMessage } from 'antd';
import { useChatStore } from '../store/chatStore';
import api from '../services/api';
import type { Message } from '../types';

export const useChat = () => {
  const {
    messages,
    addMessage,
    setLoading,
    isLoading,
    currentSessionId,
    setCurrentSessionId,
    sessions,
    setSessions,
    setMessages,
    userProfile,
  } = useChatStore();

  const [enableIntent, setEnableIntent] = useState(true);

  // 加载会话列表
  const loadSessions = async () => {
    if (!userProfile) return;

    try {
      const response = await api.getSessions(userProfile.department);
      setSessions(response.sessions || []);
    } catch (error: any) {
      console.error('加载会话列表失败:', error);
    }
  };

  // 创建新会话
  const createSession = async () => {
    if (!userProfile) return;

    try {
      const response = await api.createSession(userProfile.department);
      const newSession = response.session;

      // 更新会话列表
      setSessions([newSession, ...sessions]);

      // 切换到新会话
      setCurrentSessionId(newSession.id);
      setMessages([]);

      antdMessage.success('新会话已创建');
    } catch (error: any) {
      antdMessage.error('创建会话失败');
    }
  };

  // 切换会话
  const switchSession = async (sessionId: string) => {
    try {
      setLoading(true);
      const response = await api.getSession(sessionId);

      // 转换消息格式
      const loadedMessages: Message[] = response.messages.map((msg: any) => ({
        id: msg.id,
        role: msg.role,
        content: msg.content,
        timestamp: new Date(msg.created_at),
        sources: msg.sources,
        images: msg.images,
        fallback: msg.fallback,
        diagnostics: msg.diagnostics,
      }));

      setMessages(loadedMessages);
      setCurrentSessionId(sessionId);
    } catch (error: any) {
      antdMessage.error('加载会话失败');
    } finally {
      setLoading(false);
    }
  };

  // 删除会话
  const deleteSession = async (sessionId: string) => {
    try {
      await api.deleteSession(sessionId);

      // 从列表中移除
      setSessions(sessions.filter(s => s.id !== sessionId));

      // 如果删除的是当前会话，清空消息
      if (sessionId === currentSessionId) {
        setCurrentSessionId(null);
        setMessages([]);
      }

      antdMessage.success('会话已删除');
    } catch (error: any) {
      antdMessage.error('删除会话失败');
    }
  };

  // 重命名会话
  const renameSession = async (sessionId: string, newTitle: string) => {
    try {
      await api.updateSession(sessionId, newTitle);

      // 更新本地列表
      setSessions(sessions.map(s => s.id === sessionId ? { ...s, title: newTitle } : s));

      antdMessage.success('会话已重命名');
    } catch (error: any) {
      antdMessage.error('重命名失败');
    }
  };

  // 发送消息
  const sendMessage = async (content: string) => {
    if (!content.trim()) return;

    // 如果没有当前会话，自动创建一个
    let sessionId = currentSessionId;
    if (!sessionId && userProfile) {
      const response = await api.createSession(userProfile.department);
      sessionId = response.session.id;
      setCurrentSessionId(sessionId);
      setSessions([response.session, ...sessions]);
    }

    // 添加用户消息
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content,
      timestamp: new Date(),
    };
    addMessage(userMessage);

    setLoading(true);

    // 创建临时的思考消息
    const thinkingMessageId = (Date.now() + 1).toString();
    const thinkingMessage: Message = {
      id: thinkingMessageId,
      role: 'assistant',
      content: '正在思考...',
      timestamp: new Date(),
      isThinking: true,
    };
    addMessage(thinkingMessage);

    try {
      let finalContent = '';
      let streamFailed = false;
      let finalSources: any[] = [];
      let finalImages: any[] = [];
      let finalFallback = false;
      let finalDiagnostics: Message['diagnostics'] = null;
      let thinkingSteps: string[] = [];

      // 调用流式 API
      await api.streamChat(
        content,
        enableIntent,
        sessionId,
        // onThinking
        (text: string) => {
          thinkingSteps.push(text);
          // 更新思考消息
          setMessages((prev: Message[]) =>
            prev.map((msg: Message) =>
              msg.id === thinkingMessageId
                ? { ...msg, content: thinkingSteps.join('\n'), thinkingSteps }
                : msg
            )
          );
        },
        // onAnswerChunk - 流式接收答案片段
        (text: string) => {
          finalContent += text;
          // 实时更新答案内容
          setMessages((prev: Message[]) =>
            prev.map((msg: Message) =>
              msg.id === thinkingMessageId
                ? { ...msg, content: finalContent, isThinking: false }
                : msg
            )
          );
        },
        // onAnswer - 接收完整答案和来源
        (data: {
          content: string;
          sources: any[];
          images: any[];
          fallback?: boolean;
          diagnostics?: Message['diagnostics'];
        }) => {
          finalContent = data.content;
          finalSources = data.sources;
          finalImages = data.images;
          finalFallback = data.fallback ?? false;
          finalDiagnostics = data.diagnostics ?? null;
        },
        // onError
        (error: string) => {
          streamFailed = true;
          setLoading(false);
          antdMessage.error(error);
          // 替换为错误消息
          setMessages((prev: Message[]) =>
            prev.map((msg: Message) =>
              msg.id === thinkingMessageId
                ? { ...msg, content: error || '生成失败，请重试。', isThinking: false }
                : msg
            )
          );
        },
        // onDone
        () => {
          setLoading(false);
          if (streamFailed) return;
          // 替换思考消息为最终答案
          setMessages((prev: Message[]) =>
            prev.map((msg: Message) =>
              msg.id === thinkingMessageId
                ? {
                    ...msg,
                    content: finalContent.trim() ? finalContent : '未收到有效答案，请重试。',
                    sources: finalSources,
                    images: finalImages,
                    fallback: finalFallback,
                    diagnostics: finalDiagnostics,
                    isThinking: false,
                    thinkingSteps,
                  }
                : msg
            )
          );
          setLoading(false);

          // 刷新会话列表
          loadSessions();
        }
      );
    } catch (error: any) {
      antdMessage.error(error.message || '发送失败，请重试');

      // 替换为错误消息
      setMessages((prev: Message[]) =>
        prev.map((msg: Message) =>
          msg.id === thinkingMessageId
            ? { ...msg, content: error.message || '发送失败，请稍后重试。', isThinking: false }
            : msg
        )
      );
      setLoading(false);
    }
  };

  // 初始加载会话列表
  useEffect(() => {
    if (userProfile) {
      loadSessions();
    }
  }, [userProfile]);

  return {
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
    loadSessions,
  };
};

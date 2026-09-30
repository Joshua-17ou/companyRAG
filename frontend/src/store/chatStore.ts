import { create } from 'zustand';
import type { Message, UserProfile } from '../types';

interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

interface ChatStore {
  messages: Message[];
  userProfile: UserProfile | null;
  isLoading: boolean;
  currentSessionId: string | null;
  sessions: ChatSession[];

  // Actions
  addMessage: (message: Message) => void;
  clearMessages: () => void;
  setUserProfile: (profile: UserProfile | null) => void;
  setLoading: (loading: boolean) => void;
  setCurrentSessionId: (sessionId: string | null) => void;
  setSessions: (sessions: ChatSession[]) => void;
  setMessages: (messages: Message[] | ((prev: Message[]) => Message[])) => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  messages: [],
  userProfile: (() => {
    const department = localStorage.getItem('user_dept');
    return department && ['销售', '财务', '行政'].includes(department)
      ? { department }
      : null;
  })(),
  isLoading: false,
  currentSessionId: null,
  sessions: [],

  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),

  clearMessages: () => set({ messages: [], currentSessionId: null }),

  setUserProfile: (profile) => {
    set({ userProfile: profile });
    if (profile) {
      localStorage.setItem('user_dept', profile.department);
    } else {
      localStorage.removeItem('user_dept');
    }
  },

  setLoading: (loading) => set({ isLoading: loading }),

  setCurrentSessionId: (sessionId) => set({ currentSessionId: sessionId }),

  setSessions: (sessions) => set({ sessions }),

  setMessages: (messages) =>
    set((state) => ({
      messages: typeof messages === 'function' ? messages(state.messages) : messages,
    })),
}));

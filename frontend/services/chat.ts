const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatResponse {
  answer: string;
  conversation_id: number;
  conversation_history: Message[];
}

export async function sendChatMessage({
  documentId,
  question,
  conversationHistory,
  token,
  provider = 'groq',
}: {
  documentId: number;
  question: string;
  conversationHistory: Message[];
  token: string;
  provider?: 'groq' | 'openai';
}): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      document_id: documentId,
      question,
      provider,
      conversation_history: conversationHistory,
    }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Chat request failed');
  }
  return res.json();
}

export interface ConversationRecord {
  id: number;
  question: string;
  answer: string;
  created_at: string;
  conversation_history: Message[];
}

export async function getChatHistory(documentId: number, token: string): Promise<ConversationRecord[]> {
  const res = await fetch(`${API_BASE}/api/chat/history/${documentId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Failed to fetch chat history');
  }
  return res.json();
}

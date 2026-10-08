export interface PublicConfig {
  tenant: string;
  brand: { name: string; tagline: string; city: string };
  contact: { phone: string; email: string; hours: string };
  ui: { welcome_title: string; welcome_body: string; suggestions: string[]; disclaimer: string };
  limits: { max_message_chars: number };
}

export interface Source {
  id: string;
  score: number;
  question: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  messageId?: string;
  rating?: "up" | "down";
  status?: "streaming" | "done" | "error" | "stopped";
  tool?: string | null;
}

export type StreamEvent =
  | { event: "meta"; data: { session_id: string; message_id: string; request_id: string } }
  | { event: "delta"; data: { text: string } }
  | { event: "tool"; data: { name: string; status: "running" | "done" | "error" } }
  | { event: "sources"; data: { sources: Source[] } }
  | { event: "done"; data: { message_id: string; model: string; tools_used: string[]; latency_ms: number } }
  | { event: "error"; data: { code: string; message: string } };

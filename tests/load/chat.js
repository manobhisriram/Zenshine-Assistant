// k6 load test for the chat endpoint.  k6 run -e BASE_URL=https://chat.example.com tests/load/chat.js
// Measures time-to-first-byte (SSE headers + first token) and error rate under ramping virtual users.
// NOTE: this calls the real Anthropic API through your deployment and costs money; start small.
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";

const BASE = __ENV.BASE_URL || "http://localhost:8000";
const ttfb = new Trend("chat_ttfb_ms", true);
const failed = new Rate("chat_failed");

export const options = {
  scenarios: {
    ramp: {
      executor: "ramping-vus",
      stages: [
        { duration: "1m", target: 20 },
        { duration: "3m", target: 100 },
        { duration: "1m", target: 0 },
      ],
    },
  },
  thresholds: {
    chat_failed: ["rate<0.02"],
    chat_ttfb_ms: ["p(95)<3000"],
    http_req_failed: ["rate<0.05"],
  },
};

const QUESTIONS = [
  "How much does lawn cleaning cost?",
  "What is the price for house cleaning and kitchen cleaning together for a first time customer?",
  "Do you offer same day service?",
  "What are your working hours?",
  "How can I pay?",
];

export default function () {
  const q = QUESTIONS[Math.floor(Math.random() * QUESTIONS.length)];
  const res = http.post(`${BASE}/v1/chat/stream`, JSON.stringify({ message: q }), {
    headers: { "Content-Type": "application/json", "X-Forwarded-For": `10.${__VU % 250}.${__ITER % 250}.1` },
    timeout: "60s",
  });
  ttfb.add(res.timings.waiting);
  const ok = check(res, {
    "status 200": (r) => r.status === 200,
    "has done event": (r) => typeof r.body === "string" && r.body.includes("event: done"),
  });
  failed.add(!ok);
  sleep(2 + Math.random() * 4);
}

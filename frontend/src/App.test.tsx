import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

const config = {
  tenant: "zenshine",
  brand: { name: "ZenShine Pro", tagline: "tag", city: "Chennai" },
  contact: { phone: "+91 98765 43210", email: "a@b.c", hours: "x" },
  ui: { welcome_title: "Welcome", welcome_body: "Ask me", suggestions: ["Lawn cleaning cost?"], disclaimer: "Call {phone}" },
  limits: { max_message_chars: 1200 },
};

function sseResponse(frames: string[]) {
  const enc = new TextEncoder();
  const stream = new ReadableStream({
    start(c) {
      frames.forEach((f) => c.enqueue(enc.encode(f)));
      c.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
}
const ev = (e: string, d: unknown) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`;

afterEach(() => vi.restoreAllMocks());

describe("App", () => {
  it("shows welcome content and streams an answer", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/v1/config")) return new Response(JSON.stringify(config), { status: 200 });
      return sseResponse([
        ev("meta", { session_id: "s".repeat(12), message_id: "m".repeat(12), request_id: "r" }),
        ev("delta", { text: "It costs " }),
        ev("delta", { text: "₹800." }),
        ev("sources", { sources: [{ id: "a", score: 0.9, question: "Lawn price?" }] }),
        ev("done", { message_id: "m".repeat(12), model: "x", tools_used: [], latency_ms: 5 }),
      ]);
    });
    render(<App />);
    expect(await screen.findByText("Welcome")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Lawn cleaning cost?" }));
    expect(await screen.findByText("It costs ₹800.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /show sources/i })).toBeInTheDocument());
  });

  it("surfaces a friendly message when rate limited", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("/v1/config")) return new Response(JSON.stringify(config), { status: 200 });
      return new Response(JSON.stringify({ error: { code: "rate_limited", message: "slow" } }), { status: 429, headers: { "Retry-After": "12" } });
    });
    render(<App />);
    await screen.findByText("Welcome");
    await userEvent.type(screen.getByLabelText("Message"), "hello{enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("wait 12s");
  });
});

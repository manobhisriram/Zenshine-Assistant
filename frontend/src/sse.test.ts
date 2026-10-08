import { SSEParser } from "./sse";

describe("SSEParser", () => {
  it("parses events split across arbitrary chunk boundaries", () => {
    const p = new SSEParser();
    const frame = 'event: delta\ndata: {"text":"héllo"}\n\n';
    const out = [];
    for (const ch of frame) out.push(...p.push(ch));
    expect(out).toEqual([{ event: "delta", data: { text: "héllo" } }]);
  });

  it("ignores comments, CRLF and malformed frames", () => {
    const p = new SSEParser();
    const out = p.push(': open\r\n\r\nevent: x\r\ndata: {bad\r\n\r\nevent: done\r\ndata: {"ok":1}\r\n\r\n');
    expect(out).toEqual([{ event: "done", data: { ok: 1 } }]);
  });
});

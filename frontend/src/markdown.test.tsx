import { render, screen } from "@testing-library/react";
import { Markdown } from "./markdown";

describe("Markdown", () => {
  it("renders lists and bold", () => {
    render(<Markdown text={"Total:\n- **House** ₹2,000\n- Kitchen ₹1,200"} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("House").tagName).toBe("STRONG");
  });

  it("never emits raw HTML or javascript: links", () => {
    const { container } = render(<Markdown text={'<img src=x onerror=alert(1)> [x](javascript:alert(1)) https://ok.example/a'} />);
    expect(container.querySelector("img")).toBeNull();
    const hrefs = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["https://ok.example/a"]);
  });

  it("links phone numbers with tel:", () => {
    const { container } = render(<Markdown text="Call +91 98765 43210 today" />);
    expect(container.querySelector("a")?.getAttribute("href")).toBe("tel:+919876543210");
  });
});

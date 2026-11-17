import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import EmptyState from "./EmptyState";

describe("empty state", () => {
  it("shows the starting question without a decorative icon tile", () => {
    const { container } = render(<EmptyState language="en" onPick={() => {}} />);

    expect(
      screen.getByRole("heading", { name: /ask about your company documents/i }),
    ).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeNull();
    expect(container.querySelector(".h-14")).toBeNull();
  });

  it("sends the clicked sample back to the caller", async () => {
    const onPick = vi.fn();
    render(<EmptyState language="en" onPick={onPick} />);

    await userEvent.click(
      screen.getByRole("button", {
        name: /how many annual leave days do employees get/i,
      }),
    );

    expect(onPick).toHaveBeenCalledOnce();
    expect(onPick).toHaveBeenCalledWith(
      "How many annual leave days do employees get?",
    );
  });

  it("uses Arabic copy and questions when the language is Arabic", () => {
    render(<EmptyState language="ar" onPick={() => {}} />);

    expect(
      screen.getByRole("heading", { name: /ابحث في مستندات شركتك/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /كم عدد أيام الإجازة السنوية للموظفين؟/,
      }),
    ).toBeInTheDocument();
  });
});

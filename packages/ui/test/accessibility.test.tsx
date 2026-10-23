import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { useState } from "react";
import { Disclosure } from "../src/primitives/index.js";
afterEach(cleanup);

test("collapsed disclosures remove their controls from the accessibility tree and keyboard focus", () => {
  function Example() {
    const [open, setOpen] = useState(false);
    return <Disclosure summary="Details" open={open} onToggle={() => setOpen(!open)}><button>Inside</button></Disclosure>;
  }
  const { container } = render(<Example />);
  expect(screen.queryByRole("button", { name: "Inside" })).toBeNull();
  expect(container.querySelector('[inert][aria-hidden="true"]')).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(screen.getByRole("button", { name: "Inside" })).toBeTruthy();
  expect(container.querySelector("[inert]")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(screen.queryByRole("button", { name: "Inside" })).toBeNull();
});

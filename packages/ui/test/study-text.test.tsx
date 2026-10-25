import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { normalizePdfSymbols, pdfFormulaPreview, studyMarkdown, StudyInline, StudySourceText, StudyText } from "../src/learn/StudyText.js";

afterEach(cleanup);
test("saved generated formulas stay separated from adjacent words", () => {
  expect(studyMarkdown("Let\\(x_i\\)be positive, so\\(x_i>0\\)."))
    .toBe("Let \\(x_i\\) be positive, so \\(x_i>0\\).");
  const { container } = render(<StudyInline text={"Let\\(x_i\\)be positive."} />);
  expect(container.firstChild?.textContent).toBe("Let ");
  expect(container.lastChild?.textContent).toBe(" be positive.");
});
test("known PDF font pieces display as standard delimiters without changing source evidence", () => {
  const raw = "Φ = \uf8eb\n\uf8ec\uf8ed x² \uf8f6\uf8f7\uf8f8\n\uf8f1\uf8f4\uf8f2\uf8f3";
  const { container } = render(<StudySourceText text={raw} />);
  expect(container.textContent).toBe("Φ = ⎛\n⎜⎝ x² ⎞⎟⎠\n⎧⎪⎨⎩");
  expect(raw).toContain("\uf8eb");
  expect(normalizePdfSymbols("x² + αᵢ − 1; private \ue123")).toBe("x² + αᵢ − 1; private \ue123");
});
test("source prose remains literal and preserves line structure", () => {
  const { container } = render(<StudySourceText text={'<script>bad()</script>\n**literal** $20'} />);
  expect(container.querySelector("script, strong")).toBeNull();
  expect(container.textContent).toBe('<script>bad()</script>\n**literal** $20');
});
test("PDF previews never present flattened fractions or matrix pieces as reconstructed formulas", () => {
  expect(pdfFormulaPreview("The basis functions are:\nGaussian φj(x) = (x−µj)22σ2j")).toBe("The basis functions are:");
  expect(pdfFormulaPreview("Φ = \uf8eb matrix \uf8f6")).toBe("");
  expect(pdfFormulaPreview("=y) =\n\uf8f1\npy if y <M− 1")).toBe("");
  expect(pdfFormulaPreview("DNA contains genetic information.")).toBeNull();
});
test.each(["$2x^2$", "\\(\\frac{1}{n}\\sum_{i=1}^{n}x_i\\)", "\\[\\begin{pmatrix}a&b\\\\c&d\\end{pmatrix}\\]", "$$x_i^2$$"])("Study renders explicit maths %s", (text) => {
  const { container } = render(<StudyText text={text} />);
  expect(container.querySelector(".katex")).toBeTruthy();
  expect(container.querySelector("math")).toBeTruthy();
});
test("quiz options render the same formula as Study prose", () => {
  const formula = "\\(P(Y=y)=\\frac{1}{n}\\sum_{i=1}^{n}I(y_i=y)\\)";
  const block = render(<StudyText text={formula} />).container.querySelector(".katex")!.outerHTML;
  cleanup();
  expect(render(<StudyInline text={formula} />).container.querySelector(".katex")!.outerHTML).toBe(block);
});
test("currency and a lone dollar stay text", () => {
  const { container } = render(<StudyText text="It costs $20 and $35. Save $2." />);
  expect(container.querySelector(".katex")).toBeNull();
  expect(container.textContent).toBe("It costs $20 and $35. Save $2.");
});

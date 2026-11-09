import { expect, test } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Welcome } from "./Welcome";
test("renders the React entry point as semantic, readable HTML", () => {
  const page = renderToStaticMarkup(<Welcome />);
  expect(page).toContain("<main>");
  expect(page).toContain("Find your people.");
});

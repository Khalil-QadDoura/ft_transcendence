import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../../app/router";
import { legalDocument } from "./LegalPage";
import i18n, { languages } from "../../i18n";
let root: Root;
let container: HTMLDivElement;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
beforeEach(() => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});
test.each(["privacy", "terms"] as const)(
  "/%s is public, complete and navigable",
  async (kind) => {
    const router = createMemoryRouter(routes, { initialEntries: [`/${kind}`] });
    await act(() => root.render(<RouterProvider router={router} />));
    expect(router.state.location.pathname).toBe(`/${kind}`);
    expect(container.querySelectorAll("h1")).toHaveLength(1);
    expect(container.querySelector("time")?.dateTime).toBe(
      kind === "privacy" ? "2026-11-17" : "2026-11-13",
    );
    expect(
      container.querySelector("article")!.textContent!.length,
    ).toBeGreaterThan(5000);
    expect(container.textContent).not.toContain("This space is taking shape");
    expect(container.querySelector('footer a[href="/privacy"]')).not.toBeNull();
    expect(container.querySelector('footer a[href="/terms"]')).not.toBeNull();
    for (const section of legalDocument(kind).sections) {
      expect(
        container.querySelector(`a[href="#${section.id}"]`),
      ).not.toBeNull();
      expect(container.querySelector(`#${section.id}`)?.textContent).toBe(
        section.title,
      );
    }
    expect(
      container.querySelector(".legal-copy [lang]")?.getAttribute("lang"),
    ).toBe("en");
    expect(container.querySelector("script")).toBeNull();
  },
);
test("legal source metadata is retained without duplicate headings", () => {
  for (const kind of ["privacy", "terms"] as const) {
    const doc = legalDocument(kind);
    expect(doc.sections.length).toBeGreaterThan(5);
    expect(doc.body).not.toMatch(/^# /m);
    expect(doc.body).not.toContain("Last updated:");
  }
});

test.each(languages)(
  "%s renders both complete legal documents with matching contents and direction",
  async (language) => {
    await i18n.changeLanguage(language);
    const router = createMemoryRouter(routes, { initialEntries: ["/privacy"] });
    await act(() => root.render(<RouterProvider router={router} />));
    for (const kind of ["privacy", "terms"] as const) {
      await act(() => router.navigate(`/${kind}`));
      const document = legalDocument(kind, language);
      expect(document.sections).toHaveLength(kind === "privacy" ? 11 : 13);
      expect(
        container.querySelector(".legal-copy [lang]")?.getAttribute("lang"),
      ).toBe(language);
      expect(
        container.querySelector(".legal-copy [dir]")?.getAttribute("dir"),
      ).toBe(language === "ar" ? "rtl" : "ltr");
      expect(container.querySelector("article")?.textContent).toContain(
        "burhan.hajili@gmail.com",
      );
      expect(
        container.querySelector("article")?.textContent?.length,
      ).toBeGreaterThan(4000);
      for (const section of document.sections) {
        expect(container.querySelector(`#${section.id}`)?.textContent).toBe(
          section.title,
        );
        expect(
          container.querySelector(`a[href="#${section.id}"]`),
        ).not.toBeNull();
      }
      if (language !== "en") {
        expect(document.body).not.toBe(legalDocument(kind).body);
        const original = container.querySelector<HTMLAnchorElement>(
          `a[href="/${kind}?original=1"]`,
        )!;
        await act(() => original.click());
        expect(
          container
            .querySelector('.legal-copy [lang="en"]')
            ?.getAttribute("dir"),
        ).toBe("ltr");
        expect(container.querySelector("article")?.textContent).toContain(
          kind === "privacy" ? "Who we are" : "Acceptance and the service",
        );
        expect(container.querySelector(`a[href="/${kind}"]`)).not.toBeNull();
      }
    }
  },
);

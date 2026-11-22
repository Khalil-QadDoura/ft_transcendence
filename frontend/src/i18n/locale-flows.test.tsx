import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import i18n, { languages } from "./index";
import { AuthContext } from "../features/auth/AuthProvider";
import { AuthForm } from "../features/auth/AuthScreens";
import { AccountSettings } from "../features/account/AccountPages";
import { LegalPage, legalDocument } from "../features/legal/LegalPage";
import { Tabs } from "../components/Tabs";
import { Input } from "../components/Input";
import { Textarea } from "../components/Textarea";
import type { AuthGateway } from "../features/auth/gateway";
import { localizeMessage } from "./copy";
import { formatSalary } from "../features/jobs/api";
import { ConversationCard } from "../features/conversations/ConversationCard";
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

test("conversation times and unread numbers follow Arabic while user text stays isolated", async () => {
  await i18n.changeLanguage("ar");
  await mount(
    <ConversationCard
      onClick={() => {}}
      conversation={{
        id: 1,
        type: "direct",
        title: "سارة / Sara",
        job_id: null,
        job_title: null,
        last_message_id: 2,
        last_message_author_id: 3,
        last_message_content: "Hello سارة 42",
        unread_count: 12,
        updated_at: new Date(Date.now() - 5 * 60_000).toISOString(),
      }}
    />,
  );
  expect(container.textContent).toContain(
    new Intl.RelativeTimeFormat("ar", { style: "short" }).format(-5, "minute"),
  );
  expect(
    container.querySelector('[data-testid="unread-badge"]')?.textContent,
  ).toBe(new Intl.NumberFormat("ar").format(12));
  expect(
    container
      .querySelector('[data-testid="conversation-snippet"]')
      ?.getAttribute("dir"),
  ).toBe("auto");
  expect(container.querySelector("bdi")?.textContent).toBe("سارة / Sara");
});
test("technical error details have a localized fallback and salary periods use the active locale", async () => {
  await i18n.changeLanguage("ar");
  expect(
    localizeMessage(
      "screens",
      "path → job_id: Input should be a valid integer",
      "jobs.failedToLoadJobs",
    ),
  ).toBe("تعذّر تحميل الوظائف. حاول مجددًا.");
  expect(
    localizeMessage(
      "screens",
      "Location permission was denied",
      "jobs.locationUnavailable",
    ),
  ).toBe("تم رفض إذن الموقع");
  expect(formatSalary(25000, "AED", "monthly")).toContain(
    new Intl.NumberFormat("ar").format(25000),
  );
  expect(formatSalary(25000, "AED", "monthly")).toContain("شهري");
});
let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  await i18n.changeLanguage("en");
  localStorage.clear();
  vi.restoreAllMocks();
});
const mount = async (node: ReactNode) =>
  act(() => root.render(<MemoryRouter>{node}</MemoryRouter>));
async function fill(name: string, value: string) {
  const input = container.querySelector<HTMLInputElement>(`[name="${name}"]`)!;
  await act(() => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
test.each(languages)(
  "%s loads every shipped namespace, including queued employer/friends copy",
  async (language) => {
    await i18n.changeLanguage(language);
    for (const namespace of [
      "common",
      "screens",
      "auth",
      "account",
      "profile",
      "people",
      "employer",
      "legal",
      "status",
      "gameRules",
    ]) {
      expect(i18n.hasResourceBundle(language, namespace)).toBe(true);
    }
    if (language !== "en") {
      for (const key of [
        "auth:welcomeBack",
        "account:accountSettings",
        "profile:save",
        "people:friendsTitle",
        "employer:create",
        "screens:chat.messages",
        "screens:jobs.title",
      ]) {
        expect(i18n.t(key)).not.toBe(i18n.t(key, { lng: "en" }));
      }
    }
  },
);
test("Arabic and Russian plurals select the appropriate form with locale-formatted numbers", async () => {
  await i18n.changeLanguage("ar");
  expect(i18n.t("screens:jobs.showingRoles", { count: 0 })).toBe(
    "لا توجد وظائف متاحة",
  );
  expect(i18n.t("screens:jobs.showingRoles", { count: 2 })).toBe(
    "وظيفتان متاحتان",
  );
  expect(i18n.t("screens:chat.unreadCount", { count: 3 })).toContain(
    new Intl.NumberFormat("ar").format(3),
  );
  await i18n.changeLanguage("ru");
  expect(i18n.t("screens:chat.charsRemaining", { count: 1 })).toContain(
    "1 символ",
  );
  expect(i18n.t("screens:chat.charsRemaining", { count: 3 })).toContain(
    "3 символа",
  );
  expect(i18n.t("screens:chat.charsRemaining", { count: 5 })).toContain(
    "5 символов",
  );
});
test("language switch preserves registration input and updates an existing validation error", async () => {
  const client: AuthGateway = {
    register: vi.fn(),
    verify: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    restore: vi.fn(),
    getStatus: () => "anonymous",
    getSessionVersion: () => 0,
    subscribe: () => () => {},
  };
  await mount(
    <AuthContext value={client}>
      <AuthForm mode="register" />
    </AuthContext>,
  );
  await fill("email", "reader@example.com");
  await fill("password", "test-password-one");
  await fill("confirm", "test-password-two");
  await act(() =>
    container
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  expect(container.textContent).toContain("Passwords must match.");
  await act(() => i18n.changeLanguage("ar"));
  expect(container.querySelector("h1")?.textContent).toBe("عرّف بنفسك.");
  expect(container.textContent).toContain("يجب أن تتطابق كلمتا المرور.");
  expect(
    container.querySelector<HTMLInputElement>('[name="email"]')?.value,
  ).toBe("reader@example.com");
  expect(
    container.querySelector<HTMLInputElement>('[name="password"]')?.value,
  ).toBe("test-password-one");
  expect(client.register).not.toHaveBeenCalled();
});
test("account settings reacts to switching without losing the route", async () => {
  await mount(<AccountSettings />);
  await act(() => i18n.changeLanguage("az"));
  expect(container.querySelector("h1")?.textContent).toBe("Hesab ayarları.");
  await act(() => i18n.changeLanguage("ar"));
  expect(container.querySelector("h1")?.textContent).toBe("إعدادات الحساب.");
});
test("Arabic legal interface identifies and isolates the unchanged English original", async () => {
  const original = legalDocument("privacy").body;
  await i18n.changeLanguage("ar");
  await mount(<LegalPage kind="privacy" />);
  expect(container.querySelector("h1")?.textContent).toBe("سياسة الخصوصية");
  expect(container.textContent).toContain(
    "الوثيقة المعتمدة: النسخة الإنجليزية الأصلية.",
  );
  expect(
    container.querySelector('.legal-copy [lang="en"]')?.getAttribute("dir"),
  ).toBe("ltr");
  expect(legalDocument("privacy").body).toBe(original);
});
test.each(["ltr", "rtl"])(
  "%s tab arrows follow visual direction, skip disabled tabs, support Home/End",
  async (direction) => {
    await mount(
      <div dir={direction}>
        <Tabs
          tabs={[
            { id: "a", label: "A", content: "first" },
            { id: "b", label: "B", content: "disabled", disabled: true },
            { id: "c", label: "C", content: "last" },
          ]}
        />
      </div>,
    );
    const tabs = container.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    const key = async (button: HTMLButtonElement, value: string) =>
      act(() =>
        button.dispatchEvent(
          new KeyboardEvent("keydown", { key: value, bubbles: true }),
        ),
      );
    await key(tabs[0], direction === "rtl" ? "ArrowLeft" : "ArrowRight");
    expect(document.activeElement).toBe(tabs[2]);
    expect(tabs[2].getAttribute("aria-selected")).toBe("true");
    await key(tabs[2], "Home");
    expect(document.activeElement).toBe(tabs[0]);
    await key(tabs[0], "End");
    expect(document.activeElement).toBe(tabs[2]);
    await key(tabs[2], direction === "rtl" ? "ArrowRight" : "ArrowLeft");
    expect(document.activeElement).toBe(tabs[0]);
  },
);
test("credentials keep LTR order while free text chooses its own direction", async () => {
  await i18n.changeLanguage("ar");
  await mount(
    <>
      <Input name="email" type="email" />
      <Input name="password" type="password" />
      <Input name="name" />
      <Textarea />
    </>,
  );
  expect(container.querySelector('[name="email"]')?.getAttribute("dir")).toBe(
    "ltr",
  );
  expect(
    container.querySelector('[name="password"]')?.getAttribute("dir"),
  ).toBe("ltr");
  expect(container.querySelector('[name="name"]')?.getAttribute("dir")).toBe(
    "auto",
  );
  expect(container.querySelector("textarea")?.getAttribute("dir")).toBe("auto");
});

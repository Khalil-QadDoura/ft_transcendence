import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "../../api/client";
import { JobCard } from "../jobs/JobCard";
import type { Job } from "../jobs/types";
import { CompanyPage } from "./CompanyPage";
import { companyApi, companyLogoApi, type Company } from "./api";

const sampleCompany: Company = {
  id: 12,
  owner_user_id: 7,
  name: "Abu Dhabi Robotics",
  description: "Building autonomous systems in the UAE.",
  logo_object_key: null,
  logo_url: null,
  status: "active",
  country: "UAE",
  city: "Abu Dhabi",
  district: "Al Maryah",
  country_code: "AE",
  created_at: "2026-11-18T08:00:00Z",
  updated_at: "2026-11-18T08:00:00Z",
};

let root: Root;
let container: HTMLDivElement;
let cache: QueryClient;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  cache = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
});

afterEach(async () => {
  await act(() => root.unmount());
  cache.clear();
  container.remove();
  vi.restoreAllMocks();
});

async function renderPage() {
  await act(async () => {
    root.render(
      <QueryClientProvider client={cache}>
        <MemoryRouter>
          <CompanyPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

async function fill(name: string, value: string) {
  const field = container.querySelector<HTMLInputElement | HTMLTextAreaElement>(
    `[name="${name}"]`,
  )!;
  const proto =
    field instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  await act(() => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function submitForm() {
  await act(async () => {
    container
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

function clickButtonByText(label: string) {
  const button = Array.from(container.querySelectorAll("button")).find((btn) =>
    btn.textContent?.includes(label),
  );
  if (!button) throw new Error(`Button containing "${label}" not found`);
  return act(async () => {
    button.click();
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

test("users without a company see a create company CTA without any error", async () => {
  vi.spyOn(companyApi, "get").mockResolvedValue(null);
  await renderPage();

  expect(container.textContent).toContain("No company profile yet");
  expect(container.textContent).toContain("Create company");
  expect(container.querySelector('[role="alert"]')).toBeNull();
});

test("employer can create a company and sees validation errors next to fields", async () => {
  vi.spyOn(companyApi, "get").mockResolvedValue(null);
  const createSpy = vi
    .spyOn(companyApi, "create")
    .mockRejectedValueOnce(
      new ApiError(422, "422", "body → name: Company name already reserved"),
    )
    .mockResolvedValueOnce(sampleCompany);

  await renderPage();
  await clickButtonByText("Create company");

  // Client-side required check prevents empty submission
  await submitForm();
  expect(createSpy).not.toHaveBeenCalled();
  expect(container.textContent).toContain("This field cannot be empty.");

  await fill("name", "Abu Dhabi Robotics");
  await fill("description", "Building autonomous systems in the UAE.");
  await fill("country", "UAE");
  await fill("city", "Abu Dhabi");
  await fill("district", "Al Maryah");

  // First submit triggers server 422 mapped onto the name field
  await submitForm();
  expect(createSpy).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("Company name already reserved");

  // Second submit succeeds and transitions into the company editor
  await submitForm();
  expect(createSpy).toHaveBeenCalledTimes(2);
  expect(container.textContent).toContain("Abu Dhabi Robotics");
  expect(container.textContent).toContain("Your company profile is live.");
});

test("employer can edit company details and sees API validation errors inline", async () => {
  vi.spyOn(companyApi, "get").mockResolvedValue(sampleCompany);
  const patchSpy = vi.spyOn(companyApi, "patch").mockResolvedValue({
    ...sampleCompany,
    name: "WOZU Robotics",
    city: "Dubai",
    country_code: "AE",
  });

  await renderPage();
  await fill("name", "WOZU Robotics");
  await fill("city", "Dubai");
  await fill("country_code", "ZZ");

  // Client schema rejects unsupported country code
  await submitForm();
  expect(patchSpy).not.toHaveBeenCalled();
  expect(container.textContent).toContain(
    "Enter a supported two-letter ISO country code",
  );

  await fill("country_code", "AE");
  await submitForm();
  expect(patchSpy).toHaveBeenCalledWith({
    name: "WOZU Robotics",
    country: "UAE",
    city: "Dubai",
    district: "Al Maryah",
    country_code: "AE",
  });
  expect(container.textContent).toContain("Company details updated.");
});

test("logo upload checks type and size, shows preview and progress, and refreshes logo_url", async () => {
  const createUrl = vi
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:logo-preview");
  const revokeUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {
    /* noop */
  });

  vi.spyOn(companyApi, "get")
    .mockResolvedValueOnce(sampleCompany)
    .mockResolvedValueOnce({
      ...sampleCompany,
      logo_object_key: "logos/12/new.png",
      logo_url: "https://localhost/files/logos/12/new.png",
    });

  const uploadSpy = vi
    .spyOn(companyLogoApi, "upload")
    .mockImplementation(async (_file, _signal, onProgress) => {
      onProgress(60);
      await new Promise((resolve) => setTimeout(resolve, 10));
      onProgress(100);
    });

  await renderPage();
  const fileInput = container.querySelector<HTMLInputElement>(
    "#company-logo-input",
  )!;

  const selectFile = async (file: File) => {
    await act(async () => {
      Object.defineProperty(fileInput, "files", {
        configurable: true,
        value: [file],
      });
      fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    });
  };

  // Rejects invalid MIME type
  await selectFile(new File(["hello"], "logo.txt", { type: "text/plain" }));
  expect(container.textContent).toContain("Choose a JPG, PNG or WebP image.");

  // Rejects oversized image (> 5 MiB)
  const bigFile = new File([new Uint8Array(5 * 1024 * 1024 + 1)], "huge.png", {
    type: "image/png",
  });
  await selectFile(bigFile);
  expect(container.textContent).toContain("no larger than 5 MB");

  // Accepts valid PNG, shows preview, uploads with progress, refreshes logo_url
  const validPng = new File([new Uint8Array([137, 80, 78, 71])], "logo.png", {
    type: "image/png",
  });
  await selectFile(validPng);
  expect(createUrl).toHaveBeenCalled();
  expect(
    container.querySelector<HTMLImageElement>(".company-logo-preview")?.src,
  ).toContain("blob:logo-preview");

  await clickButtonByText("Save logo");
  expect(uploadSpy).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain(
    "Your company logo has been updated.",
  );
  const logoImg = container.querySelector<HTMLImageElement>(
    'img[src="https://localhost/files/logos/12/new.png"]',
  );
  expect(logoImg).not.toBeNull();
  expect(revokeUrl).toHaveBeenCalled();
});

test("employer can delete company via confirmation modal and returns to empty CTA", async () => {
  vi.spyOn(companyApi, "get").mockResolvedValue(sampleCompany);
  const removeSpy = vi.spyOn(companyApi, "remove").mockResolvedValue(undefined);

  await renderPage();
  await clickButtonByText("Delete company");
  expect(container.querySelector('[role="dialog"]')).not.toBeNull();

  await clickButtonByText("Yes, delete company");
  expect(removeSpy).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("No company profile yet");
  expect(container.textContent).toContain(
    "Your company profile has been deleted.",
  );
});

test("JobCard renders company logo image when company_logo_url is provided", async () => {
  const job: Job = {
    id: 101,
    owner_id: 12,
    company_name: "Abu Dhabi Robotics",
    company_logo_url: "https://localhost/files/logos/12/logo.png",
    title: "Backend Engineer",
    description: "Build APIs.",
    status: "open",
    latitude: 24.4539,
    longitude: 54.3773,
    location: "Abu Dhabi",
    salary_type: "monthly",
    schedule: "full_time",
    urgency: "normal",
    views_count: 1,
    applications_count: 0,
    created_at: "2026-11-18T08:00:00Z",
  };

  await act(async () => {
    root.render(
      <MemoryRouter>
        <JobCard job={job} />
      </MemoryRouter>,
    );
  });

  const img = container.querySelector<HTMLImageElement>(
    'img[src="https://localhost/files/logos/12/logo.png"]',
  );
  expect(img).not.toBeNull();
  expect(img?.alt).toBe("Abu Dhabi Robotics");
});

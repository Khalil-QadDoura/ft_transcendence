import { describe, expect, it } from "vitest";
import { adultBirthDate, validationOptions } from "./validation";
import { registerSchema, loginSchema } from "../features/auth/schemas";
import {
  createProfileSchema,
  createProfilePatchSchema,
} from "../features/profile/schemas";
import {
  companyCreateSchema,
  companyUpdateSchema,
} from "../features/companies/schemas";
import { jobFieldsSchema } from "../features/jobs/schemas";
import { applicationSchema } from "../features/applications/schemas";
import { messageSchema } from "../features/conversations/schemas";
import {
  avatarSelectionSchema,
  MAX_VIDEO_BYTES,
  videoSelectionSchema,
} from "../features/media/schemas";

const auth = { email: "Ana@Example.com", password: "12345678" };
const profile = {
  first_name: " Ana ",
  last_name: "Test",
  position: "Dev",
  birth_date: "2008-11-07",
};
const today = new Date(2026, 10, 7);
const job = {
  title: "Dev",
  description: "",
  location: "Baku",
  latitude: 40,
  longitude: 49,
};
const video = {
  name: "intro.MP4",
  type: "video/mp4",
  size: MAX_VIDEO_BYTES,
  duration: 30,
};

describe("auth and calendar boundaries", () => {
  it.each([7, 8, 128, 129])("registration password length %i", (length) => {
    expect(
      registerSchema.safeParse({ ...auth, password: "🔑".repeat(length) })
        .success,
    ).toBe(length >= 8 && length <= 128);
  });
  it("normalizes email but preserves password whitespace and short login attempts", () => {
    expect(registerSchema.parse({ ...auth, password: "        " })).toEqual({
      email: "ana@example.com",
      password: "        ",
    });
    expect(loginSchema.safeParse({ ...auth, password: "" }).success).toBe(
      false,
    );
    expect(loginSchema.safeParse({ ...auth, password: "x" }).success).toBe(
      true,
    );
    expect(
      registerSchema.safeParse({ ...auth, email: "invalid" }).success,
    ).toBe(false);
  });
  it.each([
    ["2008-11-07", true],
    ["2008-11-08", false],
    ["2027-01-01", false],
    ["2008-02-30", false],
    ["not-a-date", false],
  ])("birth date %s", (value, valid) =>
    expect(adultBirthDate(today).safeParse(value).success).toBe(valid),
  );
  it("uses the backend's March 1 birthday rule for leap-day births", () => {
    expect(adultBirthDate(today).safeParse("0000-01-01").success).toBe(false);
    expect(
      adultBirthDate(new Date(2026, 1, 28)).safeParse("2008-02-29").success,
    ).toBe(false);
    expect(
      adultBirthDate(new Date(2026, 2, 1)).safeParse("2008-02-29").success,
    ).toBe(true);
  });
});

describe("domain form contracts", () => {
  it("requires onboarding fields, trims names and keeps partial PATCH semantics", () => {
    expect(createProfileSchema(today).parse(profile).first_name).toBe("Ana");
    expect(createProfileSchema(today).safeParse({}).success).toBe(false);
    expect(
      createProfileSchema(today).safeParse({ ...profile, first_name: " " })
        .success,
    ).toBe(false);
    expect(createProfilePatchSchema(today).parse({ bio: null })).toEqual({
      bio: null,
    });
    expect(createProfilePatchSchema(today).parse({})).toEqual({});
    expect(
      createProfilePatchSchema(today).safeParse({ first_name: null }).success,
    ).toBe(false);
    expect(
      createProfilePatchSchema(today).safeParse({ email: "new@example.com" })
        .success,
    ).toBe(false);
  });
  it.each([
    ["first_name", 50],
    ["last_name", 50],
    ["position", 100],
    ["bio", 500],
  ] as const)("profile %s limit", (field, max) => {
    expect(
      createProfileSchema(today).safeParse({
        ...profile,
        [field]: "a".repeat(max),
      }).success,
    ).toBe(true);
    expect(
      createProfileSchema(today).safeParse({
        ...profile,
        [field]: "a".repeat(max + 1),
      }).success,
    ).toBe(false);
  });
  it("distinguishes company creation from the required update fields", () => {
    expect(companyCreateSchema.safeParse({ name: "WOZU" }).success).toBe(true);
    expect(companyUpdateSchema.safeParse({ name: "WOZU" }).success).toBe(false);
    const company = { name: "WOZU", country: "Azerbaijan", city: "Baku" };
    expect(
      companyUpdateSchema.parse({ ...company, country_code: "az" })
        .country_code,
    ).toBe("AZ");
    expect(
      companyUpdateSchema.safeParse({ ...company, country_code: "ZZ" }).success,
    ).toBe(false);
    expect(
      companyCreateSchema.safeParse({ name: "a".repeat(151) }).success,
    ).toBe(false);
  });
  it.each([
    ["title", 200],
    ["location", 150],
  ] as const)("job %s limit", (field, max) => {
    expect(
      jobFieldsSchema.safeParse({ ...job, [field]: "a".repeat(max) }).success,
    ).toBe(true);
    expect(
      jobFieldsSchema.safeParse({ ...job, [field]: "a".repeat(max + 1) })
        .success,
    ).toBe(false);
  });
  it("validates coordinates, money and enums without converting blanks to zero", () => {
    expect(
      jobFieldsSchema.safeParse({
        ...job,
        salary_amount: 0,
        salary_currency: "AZN",
        latitude: -90,
        longitude: 180,
      }).success,
    ).toBe(true);
    for (const patch of [
      { salary_amount: -1 },
      { salary_amount: "" },
      { salary_amount: NaN },
      { salary_amount: Infinity },
      { salary_currency: "azn" },
      { salary_currency: "US" },
      { latitude: 91 },
      { longitude: -181 },
      { schedule: "unknown" },
      { title: "" },
    ]) {
      expect(jobFieldsSchema.safeParse({ ...job, ...patch }).success).toBe(
        false,
      );
    }
  });
  it("checks cover notes, messages and idempotency keys at both sides of the boundary", () => {
    expect(
      applicationSchema.safeParse({ cover_note: "a".repeat(1000) }).success,
    ).toBe(true);
    expect(
      applicationSchema.safeParse({ cover_note: "a".repeat(1001) }).success,
    ).toBe(false);
    expect(
      messageSchema.safeParse({
        content: "🔑".repeat(4000),
        idempotency_key: "a".repeat(64),
      }).success,
    ).toBe(true);
    expect(messageSchema.safeParse({ content: "a".repeat(4001) }).success).toBe(
      false,
    );
    expect(messageSchema.safeParse({ content: "" }).success).toBe(false);
    expect(
      messageSchema.safeParse({
        content: "Hi",
        idempotency_key: "a".repeat(65),
      }).success,
    ).toBe(false);
  });
  it("returns translation keys even for structural errors through resolver options", () => {
    for (const schema of [
      registerSchema,
      createProfileSchema(today),
      companyUpdateSchema,
      jobFieldsSchema,
      applicationSchema,
      messageSchema,
      videoSelectionSchema,
    ]) {
      const result = schema.safeParse(null, validationOptions);
      expect(result.success).toBe(false);
      expect(
        result.error?.issues.every((issue) =>
          issue.message.startsWith("validation."),
        ),
      ).toBe(true);
    }
  });
});

describe("media preflight", () => {
  it("accepts exactly 30 seconds/50 MiB, rejects excess and empty/invalid metadata", () => {
    expect(videoSelectionSchema.safeParse(video).success).toBe(true);
    for (const patch of [
      { size: MAX_VIDEO_BYTES + 1 },
      { size: 0 },
      { duration: 30.01 },
      { duration: 0 },
      { duration: NaN },
      { name: "intro.mov" },
      { type: "video/webm" },
    ]) {
      expect(
        videoSelectionSchema.safeParse({ ...video, ...patch }).success,
      ).toBe(false);
    }
  });
  it.each([
    ["a.jpg", "image/jpeg"],
    ["a.JPEG", "image/jpeg"],
    ["a.png", "image/png"],
    ["a.webp", "image/webp"],
  ])("accepts avatar %s", (name, type) => {
    expect(avatarSelectionSchema.safeParse({ name, type }).success).toBe(true);
  });
  it("rejects unsupported or mismatched avatar formats", () => {
    expect(
      avatarSelectionSchema.safeParse({ name: "png", type: "image/png" })
        .success,
    ).toBe(false);
    expect(
      avatarSelectionSchema.safeParse({ name: "a.svg", type: "image/svg+xml" })
        .success,
    ).toBe(false);
    expect(
      avatarSelectionSchema.safeParse({ name: "a.jpg", type: "image/png" })
        .success,
    ).toBe(false);
  });
});

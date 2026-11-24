import { z } from "zod";
import { apiClient } from "../../api/client";
import { avatarFileError, putAvatar } from "../profile/avatar";

const logoExtensions: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
};

const companySchema = z.object({
  id: z.number().int(),
  owner_user_id: z.number().int(),
  name: z.string(),
  description: z.string().nullable().optional(),
  logo_object_key: z.string().nullable().optional(),
  logo_url: z.string().nullable().optional(),
  status: z.string(),
  country: z.string().nullable().optional(),
  city: z.string().nullable().optional(),
  district: z.string().nullable().optional(),
  country_code: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

const logoTicketSchema = z.object({
  object_key: z.string().min(1),
  put_url: z.string().min(1),
  max_bytes: z.number().positive(),
});

export type Company = z.infer<typeof companySchema>;

export interface CompanyCreatePayload {
  name: string;
  description?: string | null;
  country?: string | null;
  city?: string | null;
  district?: string | null;
}

export interface CompanyUpdatePayload {
  name: string;
  country: string;
  city: string;
  district?: string | null;
  country_code?: string | null;
}

export const companyApi = {
  async get(signal?: AbortSignal): Promise<Company | null> {
    const raw = await apiClient<unknown>("/companies/me", { signal });
    if (raw === null || raw === undefined) return null;
    return companySchema.parse(raw);
  },

  async create(body: CompanyCreatePayload): Promise<Company> {
    return companySchema.parse(
      await apiClient<unknown>("/companies", {
        method: "POST",
        body,
        signal: AbortSignal.timeout(15_000),
      }),
    );
  },

  async patch(body: CompanyUpdatePayload): Promise<Company> {
    return companySchema.parse(
      await apiClient<unknown>("/companies/me", {
        method: "PATCH",
        body,
        signal: AbortSignal.timeout(15_000),
      }),
    );
  },

  async remove(): Promise<void> {
    await apiClient<void>("/companies", {
      method: "DELETE",
      signal: AbortSignal.timeout(15_000),
    });
  },
};

export const companyLogoApi = {
  fileError: avatarFileError,

  async upload(
    file: File,
    signal: AbortSignal,
    onProgress: (percent: number) => void,
  ): Promise<void> {
    if (avatarFileError(file)) throw new Error("Invalid image");
    const ext = logoExtensions[file.type];
    const ticket = logoTicketSchema.parse(
      await apiClient(`/media/company-logo/upload-url?ext=${ext}`, {
        method: "POST",
        signal,
      }),
    );
    if (file.size > ticket.max_bytes) {
      throw new Error("Image exceeds server limit");
    }
    await putAvatar(file, ticket.put_url, signal, onProgress);
    await apiClient("/media/company-logo/confirm", {
      method: "POST",
      body: { object_key: ticket.object_key },
      signal,
    });
  },
};

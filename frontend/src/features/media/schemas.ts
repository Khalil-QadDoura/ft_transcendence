import { z } from "zod";
import { choice, number, text } from "../../lib/validation";

export const MAX_VIDEO_BYTES = 50 * 1024 * 1024;
// File metadata is only a preflight check; server/storage must inspect actual bytes.
export const videoSelectionSchema = z.object({
  name: text(1).refine((name) => /\.mp4$/i.test(name), "validation.videoType"),
  type: z.literal("video/mp4", { error: "validation.videoType" }),
  size: number()
    .int("validation.number")
    .min(1, "validation.emptyFile")
    .max(MAX_VIDEO_BYTES, "validation.videoSize"),
  duration: number()
    .min(1, "validation.videoDuration")
    .max(30, "validation.videoDuration"),
});
export const avatarSelectionSchema = z
  .object({
    name: text(1),
    type: choice(["image/jpeg", "image/png", "image/webp"] as const),
  })
  .refine(
    ({ name, type }) => {
      const extension = /\.([^.]+)$/.exec(name)?.[1].toLowerCase();
      return type === "image/jpeg"
        ? extension === "jpg" || extension === "jpeg"
        : extension === type.slice(6);
    },
    { path: ["name"], message: "validation.avatarType" },
  );

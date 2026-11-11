import { z } from "zod";
import { apiClient } from "../../api/client";

export const avatarLimit = 5 * 1024 * 1024;
const extensions: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
};
export function avatarFileError(file: File): "type" | "size" | null {
  if (!extensions[file.type]) return "type";
  return file.size === 0 || file.size > avatarLimit ? "size" : null;
}
export function safeUploadUrl(raw: string, origin = window.location.origin) {
  const url = new URL(raw, origin);
  if (
    url.origin !== origin ||
    !url.pathname.startsWith("/files/") ||
    url.username ||
    url.password ||
    url.hash
  )
    throw new Error("Invalid upload destination");
  return url.href;
}
export function putAvatar(
  file: File,
  url: string,
  signal: AbortSignal,
  onProgress: (percent: number) => void,
) {
  const target = safeUploadUrl(url);
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    const finish = (error?: Error) => {
      signal.removeEventListener("abort", abort);
      if (error) reject(error);
      else resolve();
    };
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    xhr.open("PUT", target);
    xhr.timeout = 60000;
    xhr.setRequestHeader("Content-Type", file.type);
    // Signed storage URL is the credential. Never attach the API bearer token.
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () =>
      finish(
        xhr.status >= 200 && xhr.status < 300
          ? undefined
          : new Error("Upload failed"),
      );
    xhr.onerror = xhr.ontimeout = () => finish(new Error("Upload failed"));
    xhr.onabort = () => finish(new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", abort, { once: true });
    xhr.send(file);
  });
}
const ticketSchema = z.object({
  object_key: z.string().min(1),
  put_url: z.string().min(1),
  max_bytes: z.number().positive(),
});
export const avatarApi = {
  async upload(
    file: File,
    signal: AbortSignal,
    onProgress: (percent: number) => void,
  ) {
    if (avatarFileError(file)) throw new Error("Invalid image");
    const ticket = ticketSchema.parse(
      await apiClient(`/media/avatar/upload-url?ext=${extensions[file.type]}`, {
        method: "POST",
        signal,
      }),
    );
    if (file.size > ticket.max_bytes)
      throw new Error("Image exceeds server limit");
    await putAvatar(file, ticket.put_url, signal, onProgress);
    await apiClient("/media/avatar/confirm", {
      method: "POST",
      body: { object_key: ticket.object_key },
      signal,
    });
  },
};

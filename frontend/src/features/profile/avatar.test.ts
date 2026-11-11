import { beforeEach, afterEach, expect, test, vi } from "vitest";
import {
  avatarApi,
  avatarFileError,
  avatarLimit,
  putAvatar,
  safeUploadUrl,
} from "./avatar";
afterEach(() => {
  vi.unstubAllGlobals();
});
test("avatar constraints reject unsupported, empty and oversized files", () => {
  expect(
    avatarFileError(new File(["image"], "photo.png", { type: "image/png" })),
  ).toBeNull();
  expect(
    avatarFileError(
      new File(["<svg>"], "photo.svg", { type: "image/svg+xml" }),
    ),
  ).toBe("type");
  expect(
    avatarFileError(new File([], "photo.jpg", { type: "image/jpeg" })),
  ).toBe("size");
  expect(
    avatarFileError(
      new File([new Uint8Array(avatarLimit + 1)], "photo.webp", {
        type: "image/webp",
      }),
    ),
  ).toBe("size");
});
test("upload URLs cannot send image bytes outside same-origin storage", () => {
  expect(
    safeUploadUrl("/files/avatar?signature=example", "https://wozu.test"),
  ).toBe("https://wozu.test/files/avatar?signature=example");
  for (const path of [
    "https://external.test/files/a",
    "/api/users/me",
    "/files/../api/users/me",
    "https://name:pass@wozu.test/files/a",
  ])
    expect(() => safeUploadUrl(path, "https://wozu.test")).toThrow();
});
class FakeXHR {
  static last: FakeXHR;
  upload: {
    onprogress?: (event: {
      lengthComputable: boolean;
      loaded: number;
      total: number;
    }) => void;
  } = {};
  status = 200;
  timeout = 0;
  onload = () => {};
  onerror = () => {};
  ontimeout = () => {};
  onabort = () => {};
  headers: Record<string, string> = {};
  constructor() {
    FakeXHR.last = this;
  }
  open = vi.fn();
  send = vi.fn();
  setRequestHeader(key: string, value: string) {
    this.headers[key] = value;
  }
  abort() {
    this.onabort();
  }
}
beforeEach(() => {
  new FakeXHR();
});
test("raw upload reports progress, sends no bearer, and aborts with its owner", async () => {
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  const controller = new AbortController();
  const progress = vi.fn();
  const pending = putAvatar(
    new File(["x"], "photo.png", { type: "image/png" }),
    "/files/avatar",
    controller.signal,
    progress,
  );
  expect(FakeXHR.last.headers).toEqual({ "Content-Type": "image/png" });
  FakeXHR.last.upload.onprogress!({
    lengthComputable: true,
    loaded: 2,
    total: 4,
  });
  expect(progress).toHaveBeenCalledWith(50);
  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
});
test("upload confirmation follows only a successful PUT", async () => {
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          object_key: "avatar-key",
          put_url: "/files/avatar",
          max_bytes: avatarLimit,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    )
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  const pending = avatarApi.upload(
    new File(["x"], "photo.png", { type: "image/png" }),
    new AbortController().signal,
    () => {},
  );
  await vi.waitFor(() => expect(FakeXHR.last.send).toHaveBeenCalled());
  expect(fetch).toHaveBeenCalledTimes(1);
  FakeXHR.last.onload();
  await pending;
  expect(fetch.mock.calls[1][0]).toBe("/api/media/avatar/confirm");
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
    object_key: "avatar-key",
  });
});
test("failed storage PUT never confirms the object", async () => {
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  const fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        object_key: "avatar-key",
        put_url: "/files/avatar",
        max_bytes: avatarLimit,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const pending = avatarApi.upload(
    new File(["x"], "photo.png", { type: "image/png" }),
    new AbortController().signal,
    () => {},
  );
  const assertion = expect(pending).rejects.toThrow("Upload failed");
  await vi.waitFor(() => expect(FakeXHR.last.send).toHaveBeenCalled());
  FakeXHR.last.status = 403;
  FakeXHR.last.onload();
  await assertion;
  expect(fetch).toHaveBeenCalledTimes(1);
});

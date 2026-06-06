import { afterEach, describe, expect, it, vi } from "vitest";
import { extractErrorMessage, fetchLawDocument, postSearch, type SearchRequest } from "./search";

const requestBody: SearchRequest = {
  q: "民法",
  mode: "literal",
  filters: {},
  size: 20,
  page: 1,
};

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json", "X-Request-ID": "req-1" },
    ...init,
  });
}

describe("extractErrorMessage", () => {
  it("prefers detail and joins field errors", () => {
    expect(extractErrorMessage({ detail: "service unavailable" }, 503)).toBe("service unavailable");
    expect(
      extractErrorMessage({ q: ["短すぎます"], mode: "invalid", request_id: "req-1" }, 400)
    ).toBe("q: 短すぎます / mode: invalid");
    expect(extractErrorMessage(null, 500)).toBe("検索に失敗しました (500)");
  });
});

describe("postSearch", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("posts search payload and returns request id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        hits: [],
        total: 0,
        took_ms: 3,
      })
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    const result = await postSearch(requestBody, controller.signal);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/search",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
        signal: controller.signal,
      })
    );
    expect(result.requestId).toBe("req-1");
    expect(result.data.total).toBe(0);
  });

  it("throws formatted error with request id when response is not ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "bad" }, { status: 400 }))
    );

    await expect(postSearch(requestBody, new AbortController().signal)).rejects.toMatchObject({
      message: "bad",
      requestId: "req-1",
    });
  });

  it("falls back when error body is not json", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("not json", {
          status: 503,
          headers: { "X-Request-ID": "req-2" },
        })
      )
    );

    await expect(postSearch(requestBody, new AbortController().signal)).rejects.toMatchObject({
      message: "検索に失敗しました (503)",
      requestId: "req-2",
    });
  });
});

describe("fetchLawDocument", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches encoded law id with optional article", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        law_id: "民法",
        law_name: "民法",
        sections: [],
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const document = await fetchLawDocument("民法", "709");

    expect(fetchMock).toHaveBeenCalledWith("/api/laws/%E6%B0%91%E6%B3%95?article=709");
    expect(document.law_name).toBe("民法");
  });

  it("throws formatted error when document fetch fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ law_id: "missing" }, { status: 404 }))
    );

    await expect(fetchLawDocument("missing")).rejects.toThrow("law_id: missing");
  });
});

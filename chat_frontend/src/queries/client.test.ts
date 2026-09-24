import { describe, expect, it } from "vitest";
import { ApiError } from "../apiClient";
import { shouldRetryRequest } from "./client";

describe("server-state retry policy", () => {
  it("never retries a rejected request", () => {
    expect(shouldRetryRequest(0, new ApiError(401, "Unauthorized"))).toBe(false);
    expect(shouldRetryRequest(0, new ApiError(404, "Not found"))).toBe(false);
    expect(shouldRetryRequest(0, new ApiError(422, "Unprocessable Entity"))).toBe(false);
  });

  it("retries network and server failures, then gives up", () => {
    expect(shouldRetryRequest(0, new ApiError(0, "Network request failed"))).toBe(true);
    expect(shouldRetryRequest(1, new ApiError(503, "Service Unavailable"))).toBe(true);
    expect(shouldRetryRequest(2, new ApiError(503, "Service Unavailable"))).toBe(false);
  });

  it("treats an unknown failure as retryable", () => {
    expect(shouldRetryRequest(0, new Error("boom"))).toBe(true);
  });
});

import { describe, expect, it } from "vitest";
import { formatMs } from "./time";

describe("formatMs", () => {
  it("formats minutes, seconds and milliseconds", () => {
    expect(formatMs(0)).toBe("0:00.000");
    expect(formatMs(65_432)).toBe("1:05.432");
  });

  it("clamps negatives to zero", () => {
    expect(formatMs(-5)).toBe("0:00.000");
  });
});

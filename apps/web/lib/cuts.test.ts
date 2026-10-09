import { describe, expect, it } from "vitest";
import { acceptedCuts, editedDuration, isWordCut, mergeIntervals, skipTarget } from "./cuts";

const cuts = [
  { start_ms: 1000, end_ms: 2000 },
  { start_ms: 5000, end_ms: 6000 },
];

describe("cuts", () => {
  it("merges overlapping and touching intervals", () => {
    expect(
      mergeIntervals([
        { start_ms: 5, end_ms: 9 },
        { start_ms: 0, end_ms: 3 },
        { start_ms: 3, end_ms: 4 },
        { start_ms: 7, end_ms: 7 },
      ]),
    ).toEqual([
      { start_ms: 0, end_ms: 4 },
      { start_ms: 5, end_ms: 9 },
    ]);
  });

  it("uses only accepted decisions", () => {
    expect(
      acceptedCuts([
        { start_ms: 0, end_ms: 10, status: "accepted" },
        { start_ms: 20, end_ms: 30, status: "suggested" },
        { start_ms: 40, end_ms: 50, status: "rejected" },
      ]),
    ).toEqual([{ start_ms: 0, end_ms: 10 }]);
  });

  it("skips playback over cuts", () => {
    expect(skipTarget(500, cuts)).toBeNull();
    expect(skipTarget(1000, cuts)).toBe(2000);
    expect(skipTarget(1500, cuts)).toBe(2000);
    expect(skipTarget(1998, cuts)).toBeNull(); // 끝 5ms 이내는 이미 넘어간 것으로
    expect(skipTarget(5500, cuts)).toBe(6000);
  });

  it("computes edited duration", () => {
    expect(editedDuration(10_000, cuts)).toBe(8000);
  });

  it("marks words mostly inside cuts", () => {
    expect(isWordCut({ start_ms: 1100, end_ms: 1900 }, cuts)).toBe(true);
    expect(isWordCut({ start_ms: 1800, end_ms: 2400 }, cuts)).toBe(false);
    expect(isWordCut({ start_ms: 1500, end_ms: 1500 }, cuts)).toBe(true);
  });
});

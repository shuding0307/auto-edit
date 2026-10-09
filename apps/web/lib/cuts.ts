/** 컷 계산 (서버 pipeline/intervals.py·timemap.py와 같은 규칙). 시간은 원본 기준 정수 ms. */

export interface Interval {
  start_ms: number;
  end_ms: number;
}

export function mergeIntervals(items: Interval[]): Interval[] {
  const sorted = items.filter((i) => i.end_ms > i.start_ms).sort((a, b) => a.start_ms - b.start_ms);
  const out: Interval[] = [];
  for (const iv of sorted) {
    const last = out[out.length - 1];
    if (last && iv.start_ms <= last.end_ms) last.end_ms = Math.max(last.end_ms, iv.end_ms);
    else out.push({ start_ms: iv.start_ms, end_ms: iv.end_ms });
  }
  return out;
}

export function acceptedCuts(decisions: (Interval & { status: string })[]): Interval[] {
  return mergeIntervals(decisions.filter((d) => d.status === "accepted"));
}

/** 편집본 미리보기: t가 삭제 구간 안이면 그 구간 끝으로 건너뛴 시각, 아니면 null. */
export function skipTarget(t_ms: number, cuts: Interval[]): number | null {
  for (const c of cuts) {
    if (t_ms >= c.start_ms && t_ms < c.end_ms - 5) return c.end_ms;
    if (c.start_ms > t_ms) break;
  }
  return null;
}

export function editedDuration(duration_ms: number, cuts: Interval[]): number {
  return duration_ms - cuts.reduce((s, c) => s + Math.min(c.end_ms, duration_ms) - c.start_ms, 0);
}

/** 단어가 승인된 컷에 절반 이상 덮이면 삭제될 단어. */
export function isWordCut(word: Interval, cuts: Interval[]): boolean {
  const len = word.end_ms - word.start_ms;
  if (len <= 0) return cuts.some((c) => word.start_ms >= c.start_ms && word.start_ms < c.end_ms);
  const covered = cuts.reduce(
    (s, c) => s + Math.max(0, Math.min(c.end_ms, word.end_ms) - Math.max(c.start_ms, word.start_ms)),
    0,
  );
  return covered * 2 >= len;
}

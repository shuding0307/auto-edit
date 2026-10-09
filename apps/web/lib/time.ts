/** 원본 기준 정수 밀리초를 "m:ss.mmm" 으로 표시한다. */
export function formatMs(ms: number): string {
  const total = Math.max(0, Math.round(ms));
  const m = Math.floor(total / 60000);
  const s = Math.floor((total % 60000) / 1000);
  const rest = total % 1000;
  return `${m}:${String(s).padStart(2, "0")}.${String(rest).padStart(3, "0")}`;
}

"use client";

import { useEffect, useRef, useState } from "react";
import type { Decision } from "@/lib/api";
import { formatMs } from "@/lib/time";

export interface Peaks {
  per_second: number;
  peaks: number[];
}

interface Props {
  durationMs: number;
  peaks: Peaks | null;
  decisions: Decision[];
  currentMs: number;
  selectedId: string | null;
  pendingInMs: number | null;
  onSeek: (ms: number) => void;
  onSelect: (id: string) => void;
  onBoundsChange: (id: string, start_ms: number, end_ms: number) => void;
}

const WINDOW_MS = 15_000;
const MIN_LEN_MS = 40;

const FILL: Record<string, string> = {
  accepted: "bg-red-500/45 border-red-600",
  suggested: "bg-amber-400/35 border-amber-500 border-dashed",
  rejected: "bg-neutral-400/15 border-neutral-400",
};

function drawWave(canvas: HTMLCanvasElement, peaks: Peaks | null, fromMs: number, toMs: number) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  if (!peaks || toMs <= fromMs) return;
  ctx.fillStyle = getComputedStyle(canvas).color;
  const perMs = peaks.per_second / 1000;
  // 말소리는 16bit 최대치보다 훨씬 작으므로 파일 안의 최대값 기준으로 그린다
  const top = Math.max(1, ...peaks.peaks);
  for (let x = 0; x < w; x++) {
    const a = Math.floor((fromMs + ((toMs - fromMs) * x) / w) * perMs);
    const b = Math.max(a + 1, Math.floor((fromMs + ((toMs - fromMs) * (x + 1)) / w) * perMs));
    let peak = 0;
    for (let i = a; i < b && i < peaks.peaks.length; i++) peak = Math.max(peak, peaks.peaks[i]);
    const bar = Math.max(1, (peak / top) * (h - 4));
    ctx.fillRect(x, (h - bar) / 2, 1, bar);
  }
}

export default function Timeline(p: Props) {
  const overview = useRef<HTMLDivElement>(null);
  const detail = useRef<HTMLDivElement>(null);
  const overviewWave = useRef<HTMLCanvasElement>(null);
  const detailWave = useRef<HTMLCanvasElement>(null);
  const [drag, setDrag] = useState<{ id: string; edge: "start" | "end"; start: number; end: number } | null>(
    null,
  );
  const [frozenFrom, setFrozenFrom] = useState<number | null>(null);

  // 상세 창: 재생 위치를 왼쪽 1/3에 두고 따라간다. 드래그 중에는 고정.
  const maxFrom = Math.max(0, p.durationMs - WINDOW_MS);
  const from = frozenFrom ?? Math.min(maxFrom, Math.max(0, p.currentMs - WINDOW_MS / 3));
  const to = Math.min(p.durationMs, from + WINDOW_MS);

  useEffect(() => {
    if (overviewWave.current) drawWave(overviewWave.current, p.peaks, 0, p.durationMs);
  }, [p.peaks, p.durationMs]);
  useEffect(() => {
    if (detailWave.current) drawWave(detailWave.current, p.peaks, from, to);
  }, [p.peaks, from, to]);
  useEffect(() => {
    const redraw = () => {
      if (overviewWave.current) drawWave(overviewWave.current, p.peaks, 0, p.durationMs);
      if (detailWave.current) drawWave(detailWave.current, p.peaks, from, to);
    };
    window.addEventListener("resize", redraw);
    return () => window.removeEventListener("resize", redraw);
  }, [p.peaks, p.durationMs, from, to]);

  const msAt = (el: HTMLElement, clientX: number, a: number, b: number) => {
    const r = el.getBoundingClientRect();
    return Math.round(a + ((clientX - r.left) / r.width) * (b - a));
  };
  /** 시각 ms의 위치 (창 [a, b] 기준). */
  const pct = (ms: number, a: number, b: number) => `${((ms - a) / (b - a)) * 100}%`;
  /** 길이 len의 폭 (창 [a, b] 기준). 위치와 달리 a를 빼지 않는다. */
  const span = (len: number, a: number, b: number) => `${(len / (b - a)) * 100}%`;

  function startDrag(e: React.PointerEvent, d: Decision, edge: "start" | "end") {
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    setFrozenFrom(from);
    setDrag({ id: d.id, edge, start: d.start_ms, end: d.end_ms });
  }
  function moveDrag(e: React.PointerEvent) {
    if (!drag || !detail.current) return;
    const ms = Math.min(p.durationMs, Math.max(0, msAt(detail.current, e.clientX, from, to)));
    setDrag(
      drag.edge === "start"
        ? { ...drag, start: Math.min(ms, drag.end - MIN_LEN_MS) }
        : { ...drag, end: Math.max(ms, drag.start + MIN_LEN_MS) },
    );
    p.onSeek(ms);
  }
  function endDrag() {
    if (drag) p.onBoundsChange(drag.id, drag.start, drag.end);
    setDrag(null);
    setFrozenFrom(null);
  }

  const shown = p.decisions.map((d) => (drag?.id === d.id ? { ...d, start_ms: drag.start, end_ms: drag.end } : d));

  return (
    <div className="select-none" onPointerMove={moveDrag} onPointerUp={endDrag}>
      {/* 전체 */}
      <div
        ref={overview}
        className="relative h-10 cursor-pointer overflow-hidden rounded border bg-white text-neutral-400"
        onClick={(e) => overview.current && p.onSeek(msAt(overview.current, e.clientX, 0, p.durationMs))}
        aria-label="전체 타임라인"
      >
        <canvas ref={overviewWave} className="absolute inset-0 h-full w-full" />
        {shown
          .filter((d) => d.status !== "rejected")
          .map((d) => (
            <div
              key={d.id}
              className={`absolute top-0 bottom-0 ${d.status === "accepted" ? "bg-red-500/40" : "bg-amber-400/40"}`}
              style={{ left: pct(d.start_ms, 0, p.durationMs), width: span(d.end_ms - d.start_ms, 0, p.durationMs) }}
            />
          ))}
        <div
          className="absolute top-0 bottom-0 border-x-2 border-blue-500/60 bg-blue-500/5"
          style={{ left: pct(from, 0, p.durationMs), width: span(to - from, 0, p.durationMs) }}
        />
        <div className="absolute top-0 bottom-0 w-0.5 bg-blue-600" style={{ left: pct(p.currentMs, 0, p.durationMs) }} />
      </div>

      {/* 상세 */}
      <div
        ref={detail}
        className="relative mt-2 h-28 cursor-crosshair overflow-hidden rounded border bg-white text-neutral-500"
        onClick={(e) => !drag && detail.current && p.onSeek(msAt(detail.current, e.clientX, from, to))}
        aria-label="상세 타임라인"
      >
        <canvas ref={detailWave} className="absolute inset-0 h-full w-full" />
        {Array.from({ length: Math.floor(to / 1000) - Math.ceil(from / 1000) + 1 }, (_, i) => Math.ceil(from / 1000) + i).map(
          (s) => (
            <div key={s} className="absolute top-0 h-full border-l border-neutral-200" style={{ left: pct(s * 1000, from, to) }}>
              <span className="ml-0.5 text-[10px] text-neutral-400">{s}s</span>
            </div>
          ),
        )}
        {shown
          .filter((d) => d.end_ms > from && d.start_ms < to)
          .map((d) => {
            const sel = d.id === p.selectedId;
            return (
              <div
                key={d.id}
                onClick={(e) => {
                  e.stopPropagation();
                  p.onSelect(d.id);
                }}
                className={`absolute top-4 bottom-1 border ${FILL[d.status] ?? ""} ${sel ? "ring-2 ring-blue-500" : ""}`}
                style={{ left: pct(Math.max(d.start_ms, from), from, to), width: span(Math.min(d.end_ms, to) - Math.max(d.start_ms, from), from, to) }}
                title={`${d.reason} (${formatMs(d.start_ms)} → ${formatMs(d.end_ms)})`}
              >
                {sel && d.start_ms >= from && (
                  <div
                    onPointerDown={(e) => startDrag(e, d, "start")}
                    className="absolute -left-1.5 top-0 bottom-0 w-3 cursor-ew-resize rounded bg-blue-600/80"
                    aria-label="시작 경계 조정"
                  />
                )}
                {sel && d.end_ms <= to && (
                  <div
                    onPointerDown={(e) => startDrag(e, d, "end")}
                    className="absolute -right-1.5 top-0 bottom-0 w-3 cursor-ew-resize rounded bg-blue-600/80"
                    aria-label="끝 경계 조정"
                  />
                )}
              </div>
            );
          })}
        {p.pendingInMs !== null && (
          <div
            className="absolute top-4 bottom-1 bg-blue-500/25"
            style={{
              left: pct(Math.max(from, Math.min(p.pendingInMs, p.currentMs)), from, to),
              width: span(Math.abs(p.currentMs - p.pendingInMs), from, to),
            }}
          />
        )}
        <div className="absolute top-0 bottom-0 w-0.5 bg-blue-600" style={{ left: pct(p.currentMs, from, to) }} />
        {drag && (
          <div className="absolute right-1 top-1 rounded bg-blue-600 px-1.5 text-xs text-white">
            {formatMs(drag.start)} → {formatMs(drag.end)}
          </div>
        )}
      </div>
    </div>
  );
}

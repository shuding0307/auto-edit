"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Decision, type ExportFile, type Project, type Word } from "@/lib/api";
import { acceptedCuts, editedDuration, isWordCut, skipTarget } from "@/lib/cuts";
import { formatMs } from "@/lib/time";
import Timeline, { type Peaks } from "./Timeline";

const KIND_LABEL: Record<string, string> = {
  silence: "무음",
  repetition: "반복",
  false_start: "말 끊김",
  filler: "추임새",
  manual: "직접 추가",
};

interface Props {
  project: Project;
  onRender: () => void;
}

export default function Review({ project, onRender }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [words, setWords] = useState<Word[]>([]);
  const [peaks, setPeaks] = useState<Peaks | null>(null);
  const [exportsList, setExports] = useState<ExportFile[]>([]);
  const [currentMs, setCurrentMs] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [preview, setPreview] = useState(true);
  const [pendingIn, setPendingIn] = useState<number | null>(null);
  const [filter, setFilter] = useState<"all" | "suggested">("all");
  const [error, setError] = useState<string | null>(null);
  const duration = project.duration_ms ?? 0;
  const editable = project.status === "review" || project.status === "done";

  useEffect(() => {
    api.decisions(project.id).then(setDecisions).catch((e) => setError(e.message));
    api.transcript(project.id).then(setWords).catch(() => setWords([]));
    if (project.peaks_url) fetch(project.peaks_url).then((r) => r.json()).then(setPeaks).catch(() => setPeaks(null));
    if (project.status === "done") api.exports(project.id).then(setExports).catch(() => {});
  }, [project.id, project.peaks_url, project.status]);

  const cuts = useMemo(() => acceptedCuts(decisions), [decisions]);
  const counts = useMemo(() => {
    const c = { accepted: 0, suggested: 0, rejected: 0 };
    for (const d of decisions) c[d.status as keyof typeof c]++;
    return c;
  }, [decisions]);

  // 편집본 미리보기: 승인된 컷 구간을 재생 중에 건너뛴다 (렌더 없이 즉시 확인)
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    let raf = 0;
    const check = () => {
      const ms = Math.round(v.currentTime * 1000);
      if (preview && !v.paused) {
        const target = skipTarget(ms, cuts);
        if (target !== null) v.currentTime = target / 1000;
      }
      setCurrentMs(ms);
    };
    // 매 프레임 확인 (부드러운 건너뛰기). 탭이 가려져 프레임이 멈출 때를 위해 영상 이벤트도 듣는다.
    const tick = () => {
      check();
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    v.addEventListener("timeupdate", check);
    v.addEventListener("seeked", check);
    return () => {
      cancelAnimationFrame(raf);
      v.removeEventListener("timeupdate", check);
      v.removeEventListener("seeked", check);
    };
  }, [cuts, preview]);

  /** 키 입력 시점의 정확한 재생 위치 (화면 갱신 주기와 무관). */
  const nowMs = () => (video.current ? Math.round(video.current.currentTime * 1000) : currentMs);

  const seek = useCallback((ms: number) => {
    if (video.current) video.current.currentTime = Math.max(0, ms) / 1000;
    setCurrentMs(ms);
  }, []);

  const update = useCallback(
    async (id: string, body: Parameters<typeof api.patchDecision>[2]) => {
      const before = decisions;
      setDecisions((ds) => ds.map((d) => (d.id === id ? { ...d, ...body } as Decision : d)));
      try {
        const saved = await api.patchDecision(project.id, id, body);
        setDecisions((ds) => ds.map((d) => (d.id === id ? saved : d)));
      } catch (e) {
        setDecisions(before);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [decisions, project.id],
  );

  const select = useCallback(
    (id: string, jump = true) => {
      setSelected(id);
      const d = decisions.find((x) => x.id === id);
      if (d && jump) {
        video.current?.pause();
        seek(Math.max(0, d.start_ms - 1500));
      }
      listRef.current?.querySelector(`[data-id="${id}"]`)?.scrollIntoView({ block: "nearest" });
    },
    [decisions, seek],
  );

  const visible = decisions.filter((d) => filter === "all" || d.status === "suggested");

  function step(dir: 1 | -1) {
    if (!visible.length) return;
    const i = visible.findIndex((d) => d.id === selected);
    const next = visible[(i + dir + visible.length) % visible.length];
    select(next.id);
  }

  async function markOut() {
    if (pendingIn === null) return;
    const now = nowMs();
    const a = Math.min(pendingIn, now);
    const b = Math.max(pendingIn, now);
    setPendingIn(null);
    if (b - a < 40) return;
    try {
      const d = await api.addDecision(project.id, a, b);
      setDecisions((ds) => [...ds, d].sort((x, y) => x.start_ms - y.start_ms));
      setSelected(d.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  // 키보드
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.metaKey || e.ctrlKey) return;
      const v = video.current;
      switch (e.key) {
        case " ":
          e.preventDefault();
          if (v?.paused) v.play();
          else v?.pause();
          break;
        case "a":
          if (selected && editable) update(selected, { status: "accepted" });
          break;
        case "r":
          if (selected && editable) update(selected, { status: "rejected" });
          break;
        case "j":
          step(1);
          break;
        case "k":
          step(-1);
          break;
        case "p":
          setPreview((x) => !x);
          break;
        case "i":
          if (editable) setPendingIn(nowMs());
          break;
        case "o":
          if (editable) markOut();
          break;
        case "Escape":
          setPendingIn(null);
          break;
        case "ArrowLeft":
          e.preventDefault();
          seek(nowMs() - (e.shiftKey ? 1000 : 100));
          break;
        case "ArrowRight":
          e.preventDefault();
          seek(nowMs() + (e.shiftKey ? 1000 : 100));
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const sel = decisions.find((d) => d.id === selected);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <section className="min-w-0">
        <div className="flex justify-center rounded-lg bg-black">
          {project.proxy_url ? (
            <video
              ref={video}
              src={project.proxy_url}
              controls
              playsInline
              preload="auto"
              className="max-h-[52vh] w-auto max-w-full"
            />
          ) : (
            <p className="p-10 text-neutral-400">미리보기 영상이 없습니다</p>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <span className="font-mono tabular-nums">{formatMs(currentMs)}</span>
          <label className="flex cursor-pointer items-center gap-1.5">
            <input type="checkbox" checked={preview} onChange={(e) => setPreview(e.target.checked)} />
            편집본 미리보기 <kbd className="rounded border px-1 text-xs text-neutral-500">P</kbd>
          </label>
          <span className="text-neutral-600">
            {formatMs(duration).slice(0, -4)} → <b>{formatMs(editedDuration(duration, cuts)).slice(0, -4)}</b>
          </span>
          {pendingIn !== null && (
            <span className="rounded bg-blue-50 px-2 text-blue-700">
              직접 컷 시작 {formatMs(pendingIn)} — <kbd>O</kbd>로 끝
            </span>
          )}
        </div>

        <div className="mt-3">
          <Timeline
            durationMs={duration}
            peaks={peaks}
            decisions={decisions}
            currentMs={currentMs}
            selectedId={selected}
            pendingInMs={pendingIn}
            onSeek={seek}
            onSelect={(id) => select(id, false)}
            onBoundsChange={(id, start_ms, end_ms) => editable && update(id, { start_ms, end_ms })}
          />
        </div>

        {words.length > 0 && (
          <div className="mt-4 rounded-lg border bg-white p-3 leading-8">
            {words.map((w) => {
              const cut = isWordCut(w, cuts);
              const active = currentMs >= w.start_ms && currentMs < w.end_ms;
              return (
                <span
                  key={w.idx}
                  onClick={() => seek(w.start_ms)}
                  className={`cursor-pointer rounded px-0.5 hover:bg-neutral-100 ${
                    cut ? "text-neutral-400 line-through decoration-red-500" : ""
                  } ${active ? "bg-blue-100" : ""}`}
                >
                  {w.text}{" "}
                </span>
              );
            })}
          </div>
        )}
        <p className="mt-2 text-xs text-neutral-500">
          <kbd>Space</kbd> 재생 · <kbd>J</kbd>/<kbd>K</kbd> 다음/이전 후보 · <kbd>A</kbd> 승인 · <kbd>R</kbd> 거절 ·
          <kbd>I</kbd>/<kbd>O</kbd> 직접 컷 · <kbd>←</kbd><kbd>→</kbd> 0.1초 (<kbd>Shift</kbd> 1초) · 선택한 후보는 상세
          타임라인에서 양 끝을 끌어 경계 조정
        </p>
      </section>

      <aside className="flex min-h-0 flex-col rounded-lg border bg-white lg:max-h-[calc(100vh-7rem)]">
        <div className="border-b p-3">
          <div className="flex items-center justify-between">
            <b>삭제 후보 {decisions.length}개</b>
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value as typeof filter)}
              className="rounded border px-1 text-sm"
            >
              <option value="all">전체</option>
              <option value="suggested">검토 필요만 ({counts.suggested})</option>
            </select>
          </div>
          <p className="mt-1 text-xs text-neutral-500">
            승인 {counts.accepted} · 검토 필요 {counts.suggested} · 거절 {counts.rejected}
          </p>
        </div>
        <ol ref={listRef} className="min-h-0 flex-1 divide-y overflow-y-auto">
          {visible.map((d) => (
            <li
              key={d.id}
              data-id={d.id}
              onClick={() => select(d.id)}
              className={`cursor-pointer px-3 py-2 text-sm ${d.id === selected ? "bg-blue-50" : "hover:bg-neutral-50"}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs tabular-nums text-neutral-600">
                  {formatMs(d.start_ms)} · {((d.end_ms - d.start_ms) / 1000).toFixed(1)}s
                </span>
                <span
                  className={`rounded px-1.5 text-xs ${
                    d.source === "llm" ? "bg-violet-100 text-violet-700" : "bg-neutral-100 text-neutral-600"
                  }`}
                >
                  {KIND_LABEL[d.kind] ?? d.kind}
                  {d.source === "llm" && ` · ${Math.round(d.confidence * 100)}%`}
                </span>
              </div>
              {d.source !== "rule" && <p className="mt-0.5 text-neutral-700">{d.reason}</p>}
              <div className="mt-1.5 flex gap-1.5">
                {(["accepted", "rejected"] as const).map((s) => (
                  <button
                    key={s}
                    disabled={!editable}
                    onClick={(e) => {
                      e.stopPropagation();
                      update(d.id, { status: d.status === s ? "suggested" : s });
                    }}
                    className={`rounded border px-2 py-0.5 text-xs disabled:opacity-50 ${
                      d.status === s
                        ? s === "accepted"
                          ? "border-red-600 bg-red-600 text-white"
                          : "border-neutral-600 bg-neutral-600 text-white"
                        : "hover:bg-neutral-100"
                    }`}
                  >
                    {s === "accepted" ? "자르기" : "남기기"}
                  </button>
                ))}
                {d.status === "suggested" && <span className="self-center text-xs text-amber-600">검토 필요</span>}
              </div>
            </li>
          ))}
        </ol>
        <div className="border-t p-3">
          {error && (
            <p className="mb-2 rounded bg-red-50 p-2 text-xs text-red-700" onClick={() => setError(null)}>
              {error}
            </p>
          )}
          {sel && (
            <p className="mb-2 text-xs text-neutral-500">
              선택: {formatMs(sel.start_ms)} → {formatMs(sel.end_ms)}
            </p>
          )}
          <button
            disabled={!editable}
            onClick={onRender}
            className="w-full rounded-md bg-blue-600 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            승인된 {counts.accepted}개 컷으로 렌더
          </button>
          {counts.suggested > 0 && (
            <p className="mt-1.5 text-center text-xs text-amber-700">
              검토 필요 {counts.suggested}개는 렌더에 반영되지 않습니다
            </p>
          )}
          {exportsList.length > 0 && (
            <div className="mt-3 space-y-1 text-sm">
              <p className="font-medium">내보낸 파일</p>
              {exportsList.map((e) => (
                <a key={e.url} href={e.url} className="block text-blue-700 underline">
                  {e.format === "mp4" ? "편집된 영상 (MP4)" : "컷 목록 (JSON)"} ·{" "}
                  {new Date(e.created_at).toLocaleString("ko-KR")}
                </a>
              ))}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

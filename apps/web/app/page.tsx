"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, uploadToS3, type Project } from "@/lib/api";
import { formatMs } from "@/lib/time";

const STATUS_LABEL: Record<string, string> = {
  created: "업로드 대기",
  uploaded: "업로드됨",
  analyzing: "분석 중",
  review: "검토 대기",
  rendering: "렌더 중",
  done: "완료",
  failed: "실패",
};

export default function Home() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    api.listProjects().then(setProjects).catch((e) => setError(`API에 연결할 수 없습니다: ${e.message}`));
  }, []);

  async function upload(file: File) {
    setError(null);
    if (!/\.(mp4|mov)$/i.test(file.name)) return setError("MP4 또는 MOV 파일만 올릴 수 있습니다.");
    if (file.size > 500 * 1024 * 1024) return setError("파일이 500MB를 넘습니다.");
    try {
      setProgress(0);
      const created = await api.createProject(file);
      await uploadToS3(created.upload_url, created.upload_headers, file, setProgress);
      await api.analyze(created.project.id);
      router.push(`/projects/${created.project.id}`);
    } catch (e) {
      setProgress(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="text-2xl font-semibold">AI Cut Editor</h1>
      <p className="mt-1 text-neutral-600">말하는 영상의 무음·말실수를 찾아 자르고, 검토한 뒤 내보냅니다.</p>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files[0];
          if (f && progress === null) upload(f);
        }}
        className={`mt-6 rounded-lg border-2 border-dashed p-10 text-center transition ${
          dragging ? "border-blue-500 bg-blue-50" : "border-neutral-300 bg-white"
        }`}
      >
        {progress === null ? (
          <>
            <p className="text-neutral-700">영상 파일을 끌어다 놓거나</p>
            <button
              onClick={() => input.current?.click()}
              className="mt-3 rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700"
            >
              파일 선택
            </button>
            <p className="mt-3 text-sm text-neutral-500">MP4·MOV, 최대 500MB · 10분</p>
          </>
        ) : (
          <div>
            <p className="text-neutral-700">
              {progress < 1 ? `업로드 중… ${Math.round(progress * 100)}%` : "분석 시작 중…"}
            </p>
            <div className="mx-auto mt-3 h-2 max-w-sm overflow-hidden rounded bg-neutral-200">
              <div className="h-full bg-blue-600 transition-all" style={{ width: `${progress * 100}%` }} />
            </div>
          </div>
        )}
        <input
          ref={input}
          type="file"
          accept="video/mp4,video/quicktime,.mov,.mp4"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
        />
      </div>
      {error && <p className="mt-3 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      <h2 className="mt-10 text-lg font-semibold">최근 프로젝트</h2>
      {projects === null && !error && <p className="mt-2 text-neutral-500">불러오는 중…</p>}
      {projects?.length === 0 && <p className="mt-2 text-neutral-500">아직 없습니다.</p>}
      <ul className="mt-2 divide-y rounded-lg border bg-white">
        {projects?.map((p) => (
          <li key={p.id}>
            <Link href={`/projects/${p.id}`} className="flex items-center justify-between px-4 py-3 hover:bg-neutral-50">
              <span>
                <span className="font-medium">{p.title}</span>
                <span className="ml-2 text-sm text-neutral-500">
                  {p.duration_ms ? formatMs(p.duration_ms).slice(0, -4) : ""}
                </span>
              </span>
              <span
                className={`rounded px-2 py-0.5 text-xs ${
                  p.status === "failed"
                    ? "bg-red-100 text-red-700"
                    : p.status === "done"
                      ? "bg-green-100 text-green-700"
                      : "bg-neutral-100 text-neutral-700"
                }`}
              >
                {STATUS_LABEL[p.status] ?? p.status}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}

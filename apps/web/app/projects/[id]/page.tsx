"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Review from "@/components/Review";
import { api, type Project } from "@/lib/api";

const BUSY = new Set(["created", "uploaded", "analyzing", "rendering"]);

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => api.getProject(id).then(setProject).catch((e) => setError(e.message)), [id]);

  useEffect(() => {
    load();
  }, [load]);

  // 분석·렌더 중에는 2초마다 진행률 폴링
  useEffect(() => {
    if (!project || !BUSY.has(project.status)) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [project, load]);

  async function retry() {
    try {
      setProject(await api.analyze(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function render() {
    try {
      setProject(await api.render(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <main className="mx-auto max-w-7xl px-4 py-4">
      <header className="mb-4 flex items-center gap-3">
        <Link href="/" className="text-sm text-blue-700 hover:underline">
          ← 프로젝트
        </Link>
        <h1 className="truncate text-lg font-semibold">{project?.title ?? "…"}</h1>
      </header>

      {error && <p className="mb-3 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {project && project.status === "analyzing" && <Progress project={project} title="분석 중" />}
      {project && project.status === "rendering" && <Progress project={project} title="렌더링 중" />}
      {project && project.status === "created" && (
        <p className="text-neutral-600">업로드가 끝나지 않았습니다. 처음 화면에서 다시 올려 주세요.</p>
      )}
      {project?.status === "failed" && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="font-medium text-red-800">처리에 실패했습니다</p>
          <p className="mt-1 break-all text-sm text-red-700">{project.error}</p>
          <button onClick={retry} className="mt-3 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white">
            다시 분석
          </button>
        </div>
      )}
      {project && (project.status === "review" || project.status === "done") && (
        <>
          {project.status === "done" && (
            <p className="mb-3 rounded bg-green-50 p-2 text-sm text-green-800">
              렌더가 끝났습니다. 오른쪽 아래에서 내려받을 수 있고, 후보를 고쳐 다시 렌더할 수도 있습니다.
            </p>
          )}
          {project.error && (
            <p className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700">직전 렌더 실패: {project.error}</p>
          )}
          <Review project={project} onRender={render} />
        </>
      )}
    </main>
  );
}

function Progress({ project, title }: { project: Project; title: string }) {
  const job = project.job;
  const pct = Math.round((job?.progress ?? 0) * 100);
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <p className="text-lg font-medium">{title}</p>
      <p className="mt-1 text-sm text-neutral-600">{job?.stage || "대기 중"}</p>
      <div className="mt-4 h-2 overflow-hidden rounded bg-neutral-200">
        <div className="h-full bg-blue-600 transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-xs text-neutral-500">{pct}%</p>
    </div>
  );
}

import { useEffect, useRef } from "react";
import { useLiveSocket } from "@/hooks/useLiveSocket";
import type { Job } from "@/types/api";

/** Follow a background job over /ws/jobs/{id}; `onFinish` fires once when it completes, fails or is cancelled. */
export function useJob(jobId: string | null, onFinish?: (job: Job) => void): Job | null {
  const { data } = useLiveSocket<{ type: "job"; job: Job; finished: boolean }>(jobId ? `/ws/jobs/${jobId}` : null);
  const fired = useRef<string | null>(null);
  const cb = useRef(onFinish);
  cb.current = onFinish;
  const job = data?.job && data.job.id === jobId ? data.job : null;
  useEffect(() => {
    if (job && ["completed", "failed", "cancelled"].includes(job.status) && fired.current !== job.id) {
      fired.current = job.id;
      cb.current?.(job);
    }
  }, [job]);
  return job;
}

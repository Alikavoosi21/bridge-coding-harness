'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useBackend } from '@/lib/backend';
import { createBrowserClient } from '@/lib/harness/browser';
import type { HarnessTaskSummary } from '@/lib/harness/client';
import type { TaskState } from '@/lib/harness/schema';

/**
 * The recent task list, read from the durable product store.
 *
 * This is a read: it never starts a task and never resumes one. The sidebar and
 * P02 share it so both show the same five/normal rows in the same order.
 */
export function useTaskList(options: { limit?: number; poll?: boolean; status?: TaskState } = {}) {
  const { limit = 20, poll = true, status } = options;
  const client = useMemo(() => createBrowserClient(), []);
  const workspacePath = useBackend((s) => s.workspace?.path ?? null);
  const [items, setItems] = useState<HarnessTaskSummary[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const page = await client.listTasks({ limit, status });
      if (!mounted.current) return;
      setItems(page.items);
      setError(null);
    } catch (caught) {
      if (mounted.current) setError(caught);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [client, limit, status]);

  useEffect(() => {
    mounted.current = true;
    setLoading(true);
    refresh().catch(() => {});
    return () => {
      mounted.current = false;
    };
  }, [refresh, workspacePath]);

  useEffect(() => {
    if (!poll) return;
    // A list row is cheap to read and the backend keeps running tasks in the
    // background; this only refreshes what is already stored.
    const timer = setInterval(() => refresh().catch(() => {}), 4000);
    return () => clearInterval(timer);
  }, [poll, refresh]);

  return { items, error, loading, refresh };
}

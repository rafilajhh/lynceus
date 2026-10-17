"use client";

import { useEffect, useRef, useState } from "react";
import type { InspectionSummary } from "@/lib/api";
import { fetchFollowupSummary } from "@/lib/control-api";
import { OpsError, fetchFollowups } from "@/lib/ops-api";

/** Follow-up kinds per record id; undefined = not known (yet). */
export type FollowupKinds = Record<string, string[]>;

const CONCURRENCY = 4;

type Source = "pending" | "summary" | "per-record";

/**
 * Follow-up kinds for the rows on screen. One call to GET /followups/summary
 * covers the whole ledger (a record it does not list has no follow-ups). On
 * an older backend without it, the ledger's own `followup_kinds` are used,
 * else /inspections/{id}/followups is fetched for the visible page only, a
 * few at a time, and cached for the session. A 404 there means no follow-up
 * service at all: fetching stops and no badge is shown.
 */
export function useFollowupKinds(rows: InspectionSummary[]): FollowupKinds {
  const [kinds, setKinds] = useState<FollowupKinds>({});
  const [source, setSource] = useState<Source>("pending");
  const summary = useRef<Map<string, string[]> | null>(null);
  const requested = useRef(new Set<string>());
  const unsupported = useRef(false);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  // The page slice is a new array every render: key the effects on its ids.
  const key = rows.map((row) => row.record_id).join(",");

  useEffect(() => {
    const controller = new AbortController();
    fetchFollowupSummary(controller.signal)
      .then((map) => {
        summary.current = new Map([...map].map(([id, state]) => [id, state.kinds]));
        setSource("summary");
      })
      .catch(() => {
        if (!controller.signal.aborted) setSource("per-record");
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (source !== "summary" || !summary.current) return;
    const next: FollowupKinds = {};
    for (const row of rowsRef.current) next[row.record_id] = summary.current.get(row.record_id) ?? [];
    setKinds((prev) => ({ ...prev, ...next }));
  }, [source, key]);

  useEffect(() => {
    if (source !== "per-record") return;
    const rows = rowsRef.current;
    const fromSummary: FollowupKinds = {};
    for (const row of rows) {
      if (row.followup_kinds) fromSummary[row.record_id] = row.followup_kinds;
    }
    if (Object.keys(fromSummary).length > 0) {
      setKinds((prev) => ({ ...prev, ...fromSummary }));
    }

    const queue = rows
      .filter(
        (row) =>
          !row.followup_kinds &&
          row.decision !== "refuse_insufficient_input" &&
          !requested.current.has(row.record_id),
      )
      .map((row) => row.record_id);
    if (unsupported.current || queue.length === 0) return;
    for (const id of queue) requested.current.add(id);

    let cancelled = false;
    const worker = async () => {
      while (!cancelled && !unsupported.current) {
        const id = queue.shift();
        if (!id) return;
        try {
          const data = await fetchFollowups(id);
          // Kept even after a page change: the answer is cached, not shown.
          setKinds((prev) => ({ ...prev, [id]: data.followups.map((f) => f.kind) }));
        } catch (err) {
          if (err instanceof OpsError && err.status === 404) unsupported.current = true;
          // Any other failure: leave the row unbadged and let a later page
          // visit try again.
          else requested.current.delete(id);
        }
      }
    };
    for (let i = 0; i < CONCURRENCY; i++) void worker();
    return () => {
      cancelled = true;
      // Ids still queued were never asked: allow a later render to ask.
      for (const id of queue) requested.current.delete(id);
    };
  }, [source, key]);

  return kinds;
}

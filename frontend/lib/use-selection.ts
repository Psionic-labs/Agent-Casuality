"use client";

/* React binding for the single shared selection store: every view calls
 * useSelection() and gets the same selectedEventId, so DAG, timeline, and
 * inspector can never diverge. */

import { useSyncExternalStore } from "react";
import { selectionStore } from "./store.ts";

export function useSelection(): string | null {
  return useSyncExternalStore(
    (notify) => selectionStore.subscribe(() => notify()),
    () => selectionStore.selectedId,
    // Prerendered shell has no selection; the client subscribes on hydrate.
    () => null,
  );
}

export function selectEvent(id: string | null): void {
  selectionStore.select(id);
}

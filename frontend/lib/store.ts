/* Single shared selection store: the DAG, the timeline, and the inspector
 * all read and write the same selectedEventId — there is exactly one
 * selection state. Framework-free so it stays unit-testable with node:test;
 * React subscribes via useSyncExternalStore (see lib/use-selection.ts). */

export type SelectionListener = (id: string | null) => void;

export interface SelectionStore {
  readonly selectedId: string | null;
  select(id: string | null): void;
  subscribe(fn: SelectionListener): () => void;
}

export function createSelectionStore(): SelectionStore {
  let selectedEventId: string | null = null;
  const listeners = new Set<SelectionListener>();
  return {
    get selectedId(): string | null {
      return selectedEventId;
    },
    select(id: string | null): void {
      if (selectedEventId === id) return;
      selectedEventId = id;
      for (const fn of listeners) fn(id);
    },
    subscribe(fn: SelectionListener): () => void {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
  };
}

/** The one shared store used by the DAG, timeline, and inspector. */
export const selectionStore: SelectionStore = createSelectionStore();

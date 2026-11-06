import { create } from "zustand";

/** Whether the VOXORA server is currently reachable (drives the reconnect banner). */
export const useConnection = create<{ offline: boolean; setOffline: (v: boolean) => void }>((set) => ({
  offline: false,
  setOffline: (offline) => set((s) => (s.offline === offline ? s : { offline })),
}));

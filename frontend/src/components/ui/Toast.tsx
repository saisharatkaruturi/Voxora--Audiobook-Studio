import { create } from "zustand";
import { CheckCircle2, Info, XCircle, X } from "lucide-react";
import { cn } from "@/utils/format";

type ToastKind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastState {
  items: ToastItem[];
  push: (kind: ToastKind, message: string) => void;
  dismiss: (id: number) => void;
}

let seq = 0;
export const useToasts = create<ToastState>((set, get) => ({
  items: [],
  push: (kind, message) => {
    const id = ++seq;
    set({ items: [...get().items.slice(-3), { id, kind, message }] });
    setTimeout(() => get().dismiss(id), kind === "error" ? 8000 : 4000);
  },
  dismiss: (id) => set({ items: get().items.filter((t) => t.id !== id) }),
}));

export const toast = {
  success: (m: string) => useToasts.getState().push("success", m),
  error: (m: string) => useToasts.getState().push("error", m),
  info: (m: string) => useToasts.getState().push("info", m),
};

const icons = { success: CheckCircle2, error: XCircle, info: Info };

export function Toaster() {
  const { items, dismiss } = useToasts();
  return (
    <div aria-live="polite" className="pointer-events-none fixed inset-x-0 top-4 z-[100] flex flex-col items-center gap-2 px-4">
      {items.map((t) => {
        const Icon = icons[t.kind];
        return (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className="glass pointer-events-auto flex w-full max-w-md animate-fade-up items-start gap-3 rounded-2xl px-4 py-3 shadow-2xl"
          >
            <Icon className={cn("mt-0.5 size-4 shrink-0", t.kind === "success" && "text-sage-400", t.kind === "error" && "text-rose-400", t.kind === "info" && "text-sky-400")} />
            <p className="flex-1 text-sm text-paper-100">{t.message}</p>
            <button type="button" onClick={() => dismiss(t.id)} className="text-paper-500 hover:text-paper-100" aria-label="Dismiss">
              <X className="size-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

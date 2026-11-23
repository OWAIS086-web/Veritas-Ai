import { create } from "zustand";

export type ToastTone = "success" | "error" | "info";

export interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  detail?: string;
}

interface ToastState {
  toasts: Toast[];
  push: (tone: ToastTone, title: string, detail?: string) => void;
  dismiss: (id: number) => void;
}

let next = 1;

export const useToasts = create<ToastState>((set) => ({
  toasts: [],
  push: (tone, title, detail) => {
    const id = next++;
    set((s) => ({ toasts: [...s.toasts, { id, tone, title, detail }].slice(-4) }));
    window.setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 5000);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

export const toast = {
  success: (title: string, detail?: string) => useToasts.getState().push("success", title, detail),
  error: (title: string, detail?: string) => useToasts.getState().push("error", title, detail),
  info: (title: string, detail?: string) => useToasts.getState().push("info", title, detail),
};

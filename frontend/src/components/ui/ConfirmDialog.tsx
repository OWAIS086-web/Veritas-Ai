import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  loading?: boolean;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
}

/** Destructive-action confirmation. Radix traps focus and restores it on close. */
export function ConfirmDialog({
  open, title, description, confirmLabel, loading, onConfirm, onOpenChange,
}: ConfirmDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-bg/80 backdrop-blur-sm" />
        <Dialog.Content className="panel fixed left-1/2 top-1/2 z-50 w-[min(92vw,420px)] -translate-x-1/2 -translate-y-1/2 p-6 shadow-2xl">
          <div className="flex gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-danger" aria-hidden />
            <div className="space-y-2">
              <Dialog.Title className="text-base font-semibold">{title}</Dialog.Title>
              <Dialog.Description className="text-sm text-muted">{description}</Dialog.Description>
            </div>
          </div>
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="ghost">Cancel</Button>
            </Dialog.Close>
            <Button variant="danger" loading={loading} onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

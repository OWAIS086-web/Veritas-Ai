import { clsx } from "clsx";
import { FileUp } from "lucide-react";
import { type DragEvent, useId, useRef, useState } from "react";

export const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.docx,.xlsx,.csv,.eml,.zip";

interface DropzoneProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  compact?: boolean;
}

/** Drag-and-drop or keyboard file selection. The server decides the real file type. */
export function Dropzone({ onFiles, disabled, compact }: DropzoneProps) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (!disabled && e.dataTransfer.files.length) onFiles(Array.from(e.dataTransfer.files));
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={clsx(
        "grid-lines flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed text-center transition-colors",
        compact ? "px-4 py-5" : "px-6 py-10",
        over ? "border-evidence bg-evidence/5" : "border-line",
        disabled && "opacity-60",
      )}
    >
      <FileUp className="h-6 w-6 text-evidence" aria-hidden />
      <p className="text-sm">
        Drop documents here or{" "}
        <label htmlFor={inputId} className="cursor-pointer text-evidence underline-offset-4 hover:underline">
          browse files
        </label>
      </p>
      <p className="text-xs text-muted">PDF (digital or scanned), PNG, JPG, TIFF, DOCX, XLSX, CSV, EML or ZIP</p>
      <input
        ref={input}
        id={inputId}
        type="file"
        multiple
        accept={ACCEPT}
        disabled={disabled}
        className="sr-only"
        aria-label="Choose documents to upload"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) onFiles(files);
          if (input.current) input.current.value = "";
        }}
      />
    </div>
  );
}

import { clsx } from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}

const variants: Record<Variant, string> = {
  primary:
    "bg-primary text-bg hover:bg-primary/90 shadow-glow disabled:bg-primary/40 disabled:shadow-none",
  secondary: "border border-line bg-elevated text-ink hover:border-evidence/40 hover:text-evidence",
  ghost: "text-muted hover:bg-elevated hover:text-ink",
  danger: "border border-danger/40 bg-danger/10 text-danger hover:bg-danger/20",
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-60",
        size === "sm" ? "h-8 px-3 text-xs" : "h-10 px-4 text-sm",
        variants[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

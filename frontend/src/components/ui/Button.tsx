import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { cn } from "@/utils/format";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
type Size = "sm" | "md" | "lg";

const base =
  "inline-flex items-center justify-center gap-2 font-medium whitespace-nowrap rounded-[var(--radius-control)] transition-[background,color,box-shadow,transform] duration-200 ease-[var(--ease-out-soft)] active:scale-[0.98] disabled:opacity-45 disabled:active:scale-100 select-none";

const variants: Record<Variant, string> = {
  primary: "bg-orchid-500 text-ink-950 hover:bg-orchid-400 shadow-[0_8px_24px_-10px_rgb(196_92_255/0.7)]",
  secondary: "bg-white/[0.07] text-paper-100 hover:bg-white/[0.11] border border-white/[0.08]",
  ghost: "text-paper-300 hover:text-paper-100 hover:bg-white/[0.06]",
  subtle: "bg-white/[0.04] text-paper-300 hover:text-paper-100 hover:bg-white/[0.08]",
  danger: "bg-rose-400/12 text-rose-400 hover:bg-rose-400/20 border border-rose-400/20",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-[15px]",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button ref={ref} type={type} disabled={disabled || loading} className={cn(base, variants[variant], sizes[size], className)} {...rest}>
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export function ButtonLink({ variant = "secondary", size = "md", className, icon, children, ...rest }: LinkProps & { variant?: Variant; size?: Size; icon?: ReactNode }) {
  return (
    <Link className={cn(base, variants[variant], sizes[size], className)} {...rest}>
      {icon}
      {children}
    </Link>
  );
}

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  size?: "sm" | "md" | "lg" | "xl";
  variant?: "ghost" | "solid" | "primary";
}

const iconSizes = { sm: "size-8", md: "size-10", lg: "size-12", xl: "size-16" };

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, size = "md", variant = "ghost", className, children, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full transition-[background,color,transform] duration-200 active:scale-95 disabled:opacity-40",
        iconSizes[size],
        variant === "ghost" && "text-paper-300 hover:bg-white/[0.07] hover:text-paper-100",
        variant === "solid" && "bg-white/[0.07] text-paper-100 hover:bg-white/[0.12]",
        variant === "primary" && "bg-paper-100 text-ink-950 hover:bg-white shadow-[0_10px_30px_-10px_rgb(242_237_228/0.5)]",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});

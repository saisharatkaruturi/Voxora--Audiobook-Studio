import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/utils/format";

const control =
  "w-full rounded-[var(--radius-control)] bg-ink-900/80 border border-white/[0.08] px-3.5 text-sm text-paper-100 placeholder:text-paper-500 transition-colors hover:border-white/[0.14] focus:border-orchid-500/60 focus:outline-none focus-visible:outline-none focus:ring-2 focus:ring-orchid-500/20";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cn(control, "h-10", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cn(control, "py-3 leading-relaxed", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return (
    <div className="relative">
      <select ref={ref} className={cn(control, "h-10 appearance-none pr-9", className)} {...rest}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-paper-500" aria-hidden />
    </div>
  );
});

export function Field({ label, hint, error, children, htmlFor }: { label: string; hint?: ReactNode; error?: string | null; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-paper-300">
        {label}
      </label>
      {children}
      {error ? <p className="text-xs text-rose-400">{error}</p> : hint ? <p className="text-xs text-paper-500">{hint}</p> : null}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className={cn("flex items-start justify-between gap-4", disabled && "opacity-50")}>
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium text-paper-100">
          {label}
        </label>
        {description && <p className="mt-0.5 text-xs leading-relaxed text-paper-500">{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-200",
          checked ? "bg-orchid-500" : "bg-ink-600",
        )}
      >
        <span className={cn("inline-block size-5 rounded-full bg-[#f7f3ee] shadow transition-transform duration-200", checked ? "translate-x-[22px]" : "translate-x-0.5")} />
      </button>
    </div>
  );
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
  className,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
  label: string;
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("inline-flex flex-wrap gap-1 rounded-[var(--radius-control)] bg-ink-900/80 p-1 border border-white/[0.06]", className)}>
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "h-8 rounded-lg px-3 text-[13px] font-medium transition-colors",
            o.value === value ? "bg-white/[0.1] text-paper-50" : "text-paper-400 hover:text-paper-100",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

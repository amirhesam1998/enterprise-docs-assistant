import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from "react";

/** Buttons: solid (primary action), outline, ghost, danger. */
export function Button({
  variant = "solid",
  size = "md",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "solid" | "outline" | "ghost" | "danger";
  size?: "sm" | "md";
}) {
  const sizes = size === "sm" ? "h-8 px-3 text-[13px]" : "h-10 px-4 text-sm";
  const variants: Record<string, string> = {
    solid:
      "bg-accent text-accent-ink hover:brightness-110 active:brightness-95 shadow-sm",
    outline:
      "border border-line-strong text-ink hover:bg-panel-2 hover:border-faint",
    ghost: "text-muted hover:text-ink hover:bg-panel-2",
    danger:
      "border border-danger/40 text-danger hover:bg-danger-bg hover:border-danger/60",
  };
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-md font-medium
        transition-[filter,background-color,border-color,transform] duration-150
        disabled:opacity-50 disabled:pointer-events-none select-none
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60
        ${sizes} ${variants[variant]} ${className}`}
      {...props}
    />
  );
}

export function Chip({
  children,
  tone = "neutral",
  className = "",
  onRemove,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "creator" | "admin" | "user" | "ok" | "danger";
  className?: string;
  onRemove?: () => void;
}) {
  const tones: Record<string, string> = {
    neutral: "bg-panel-2 text-muted border-line",
    accent: "bg-accent/12 text-accent border-accent/30",
    creator: "bg-creator-bg text-creator border-creator/30",
    admin: "bg-admin-bg text-admin border-admin/30",
    user: "bg-user-bg text-user border-user/30",
    ok: "bg-ok/12 text-ok border-ok/30",
    danger: "bg-danger-bg text-danger border-danger/30",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5
        text-xs font-medium ${tones[tone]} ${className}`}
    >
      {children}
      {onRemove && (
        <button
          onClick={onRemove}
          className="-mr-1 grid h-4 w-4 place-items-center rounded-full hover:bg-black/10 dark:hover:bg-white/10"
          aria-label="Remove"
        >
          <span className="text-[13px] leading-none">×</span>
        </button>
      )}
    </span>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-muted stamp">
        {label}
      </span>
      {children}
      {hint && <span className="mt-1 block text-xs text-faint">{hint}</span>}
    </label>
  );
}

const inputCls = `w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-ink
  placeholder:text-faint transition-colors focus:border-accent focus:outline-none
  focus:ring-2 focus:ring-accent/25`;

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={inputCls} {...props} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={inputCls} {...props} />;
}

export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-line bg-panel shadow-[0_1px_0_rgba(0,0,0,0.02)] ${className}`}
    >
      {children}
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent ${className}`}
    />
  );
}

export function SectionTitle({
  eyebrow,
  title,
  children,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="mb-5 flex items-end justify-between gap-4">
      <div>
        {eyebrow && (
          <div className="stamp mb-1 text-[11px] text-accent">{eyebrow}</div>
        )}
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      </div>
      {children}
    </div>
  );
}

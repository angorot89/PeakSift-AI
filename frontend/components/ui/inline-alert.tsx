import { AlertTriangle, CircleAlert, Info } from "lucide-react";
import type { ReactNode } from "react";

type Tone = "danger" | "warning" | "info";

const styles: Record<Tone, { box: string; icon: string; Icon: typeof Info }> = {
  danger: { box: "border-danger/30 bg-danger/[0.07]", icon: "text-danger", Icon: CircleAlert },
  warning: { box: "border-warning/30 bg-warning/[0.07]", icon: "text-warning", Icon: AlertTriangle },
  info: { box: "border-border-strong bg-surface-2", icon: "text-muted", Icon: Info },
};

/** Short heading, a human explanation, and the recovery action — without turning the page red. */
export function InlineAlert({
  tone = "danger",
  title,
  children,
  action,
}: {
  tone?: Tone;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const s = styles[tone];
  return (
    <div
      role={tone === "info" ? "status" : "alert"}
      className={`flex flex-col gap-3 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${s.box}`}
    >
      <div className="flex min-w-0 gap-3">
        <s.Icon aria-hidden="true" className={`mt-0.5 size-4 shrink-0 ${s.icon}`} />
        <div className="min-w-0 text-sm">
          <p className="font-medium text-foreground">{title}</p>
          {children ? <div className="mt-0.5 break-words text-muted">{children}</div> : null}
        </div>
      </div>
      {action ? <div className="shrink-0 sm:pl-4">{action}</div> : null}
    </div>
  );
}

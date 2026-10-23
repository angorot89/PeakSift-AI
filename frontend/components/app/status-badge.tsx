import { StatusPill } from "@/components/ui/status-pill";
import { humanStatus } from "@/lib/status";

/** A job's state in creator words (Waiting · a working step · Ready · Needs attention). */
export function StatusBadge({ status, stale = false }: { status: string; stale?: boolean }) {
  const { label, tone } = humanStatus(status, stale);
  return <StatusPill tone={tone}>{label}</StatusPill>;
}

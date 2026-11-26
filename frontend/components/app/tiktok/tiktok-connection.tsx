"use client";

import { Music2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { errorMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { connectTikTok, disconnectTikTok, getTikTokStatus, tiktokOutcome } from "@/lib/tiktok";
import { useApi } from "@/lib/use-api";

/**
 * Settings: the creator's TikTok account. Shown only where this server offers TikTok, so a
 * platform that cannot be used is never advertised.
 */
export function TikTokConnection() {
  const params = useSearchParams();
  const outcome = useMemo(() => tiktokOutcome(new URLSearchParams(params.toString())), [params]);
  const { data, error, loading, reload } = useApi(getTikTokStatus);
  const [busy, setBusy] = useState<"connect" | "disconnect" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  if (!loading && data && !data.enabled && !outcome) return null;

  async function connect() {
    setBusy("connect");
    setActionError(null);
    try {
      await connectTikTok(); // leaves the page for TikTok's consent screen
    } catch (failure) {
      setActionError(errorMessage(failure));
      setBusy(null);
    }
  }

  async function disconnect() {
    setBusy("disconnect");
    setActionError(null);
    try {
      const result = await disconnectTikTok();
      setNotice(
        result.revoked_with_provider
          ? "PeakSift's access was removed on TikTok and here."
          : "The connection was removed here. TikTok did not confirm it, so also remove PeakSift under TikTok's Settings → Security → Manage app permissions.",
      );
      setConfirming(false);
      reload();
    } catch (failure) {
      setActionError(errorMessage(failure));
    } finally {
      setBusy(null);
    }
  }

  const connection = data?.connection ?? null;
  const reconnect = connection?.status === "needs_reconnect";

  return (
    <Panel
      id="tiktok"
      title={
        <span className="inline-flex items-center gap-2">
          <Music2 aria-hidden="true" className="size-4 text-accent-soft" />
          TikTok
        </span>
      }
      description="Post finished Shorts to your TikTok account. PeakSift asks only for permission to post videos — it cannot read your profile, followers or messages, and it cannot delete anything."
    >
      <div className="space-y-4">
        {outcome ? (
          <InlineAlert tone={outcome.ok ? "info" : "warning"} title={outcome.ok ? "Connected" : "Not connected"}>
            {outcome.message}
          </InlineAlert>
        ) : null}
        {notice ? <InlineAlert tone="info" title="Disconnected">{notice}</InlineAlert> : null}
        {actionError ? <InlineAlert title="That did not work">{actionError}</InlineAlert> : null}

        {loading ? (
          <div role="status" aria-label="Loading connection">
            <Skeleton className="h-16 w-full rounded-block" />
          </div>
        ) : error || !data ? (
          <ErrorState title="Connection status unavailable" message={error ?? "Try again."} onRetry={reload} />
        ) : !data.enabled ? null : connection ? (
          <div className="flex flex-col gap-3 rounded-block border border-border bg-surface-2/60 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-foreground">
                <span dir="auto" className="break-all">{connection.account_title || "Your TikTok account"}</span>
                <StatusPill tone={reconnect ? "warning" : "success"}>{reconnect ? "Needs reconnecting" : "Connected"}</StatusPill>
              </p>
              <p className="mt-0.5 text-small text-muted">
                {reconnect
                  ? "TikTok no longer accepts PeakSift's access. Connect again to post."
                  : `Connected ${formatDate(connection.connected_at)}.`}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              {reconnect ? (
                <Button onClick={connect} disabled={busy !== null}>
                  {busy === "connect" ? "Opening TikTok…" : "Reconnect"}
                </Button>
              ) : null}
              {confirming ? (
                <>
                  <Button variant="danger" onClick={disconnect} disabled={busy !== null}>
                    {busy === "disconnect" ? "Disconnecting…" : "Yes, disconnect"}
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirming(false)} disabled={busy !== null}>
                    Keep it
                  </Button>
                </>
              ) : (
                <Button variant="secondary" onClick={() => setConfirming(true)} disabled={busy !== null}>
                  Disconnect
                </Button>
              )}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-3 rounded-block border border-dashed border-border-strong p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-pretty text-muted">
              No account connected. You choose who can see each post when you publish it.
            </p>
            <Button onClick={connect} disabled={busy !== null} className="shrink-0">
              {busy === "connect" ? "Opening TikTok…" : "Connect TikTok"}
            </Button>
          </div>
        )}
        {confirming ? (
          <p className="text-small text-muted">
            PeakSift will stop posting to this account and remove its access. Posts already on TikTok stay there.
          </p>
        ) : null}
      </div>
    </Panel>
  );
}

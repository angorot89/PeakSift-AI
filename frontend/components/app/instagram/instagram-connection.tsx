"use client";

import { Camera } from "lucide-react";
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
import { connectInstagram, disconnectInstagram, getInstagramStatus, instagramOutcome } from "@/lib/instagram";
import { useApi } from "@/lib/use-api";

/**
 * Settings: the creator's Instagram professional account, through Facebook Login. Shown only
 * where this server offers Instagram.
 */
export function InstagramConnection() {
  const params = useSearchParams();
  const outcome = useMemo(() => instagramOutcome(new URLSearchParams(params.toString())), [params]);
  const { data, error, loading, reload } = useApi(getInstagramStatus);
  const [busy, setBusy] = useState<"connect" | "disconnect" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  if (!loading && data && !data.enabled && !outcome) return null;

  async function connect() {
    setBusy("connect");
    setActionError(null);
    try {
      await connectInstagram(); // leaves the page for Meta's consent screen
    } catch (failure) {
      setActionError(errorMessage(failure));
      setBusy(null);
    }
  }

  async function disconnect() {
    setBusy("disconnect");
    setActionError(null);
    try {
      const result = await disconnectInstagram();
      setNotice(
        result.revoked_with_provider
          ? "PeakSift's access was removed on Facebook and here."
          : "The connection was removed here. To remove PeakSift's access on Facebook too, open Facebook's Settings → Business integrations and remove it there.",
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
      id="instagram"
      title={
        <span className="inline-flex items-center gap-2">
          <Camera aria-hidden="true" className="size-4 text-accent-soft" />
          Instagram
        </span>
      }
      description="Post finished Shorts as Reels. Instagram needs a professional (business or creator) account linked to a Facebook Page; you connect through Facebook. PeakSift asks for permission to publish to that account and to see which Pages it is linked to — it cannot read your messages or delete anything."
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
            <Skeleton className="h-16 w-full rounded-xl" />
          </div>
        ) : error || !data ? (
          <ErrorState title="Connection status unavailable" message={error ?? "Try again."} onRetry={reload} />
        ) : !data.enabled ? null : connection ? (
          <div className="flex flex-col gap-3 rounded-block border border-border bg-surface-2/60 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-foreground">
                <span dir="auto" className="break-all">{connection.account_title || "Your Instagram account"}</span>
                <StatusPill tone={reconnect ? "warning" : "success"}>{reconnect ? "Needs reconnecting" : "Connected"}</StatusPill>
              </p>
              <p className="mt-0.5 text-small text-muted">
                {reconnect
                  ? "Instagram no longer accepts PeakSift's access. Connect again to post."
                  : `Connected ${formatDate(connection.connected_at)}.`}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              {reconnect ? (
                <Button onClick={connect} disabled={busy !== null}>
                  {busy === "connect" ? "Opening Facebook…" : "Reconnect"}
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
              No account connected. Reels posted through PeakSift are public on your professional account.
            </p>
            <Button onClick={connect} disabled={busy !== null} className="shrink-0">
              {busy === "connect" ? "Opening Facebook…" : "Connect Instagram"}
            </Button>
          </div>
        )}
        {confirming ? (
          <p className="text-small text-muted">
            PeakSift will stop posting to this account and forget its access. Reels already on Instagram stay there.
          </p>
        ) : null}
      </div>
    </Panel>
  );
}

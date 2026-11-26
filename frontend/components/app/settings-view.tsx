"use client";

import { CheckCircle2, CirclePlay, Unplug } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  AnalyticsPermissionNote,
  ConnectAnalyticsButton,
  DeleteCollectedMetrics,
} from "@/components/app/analytics/analytics-access";
import { TikTokConnection } from "@/components/app/tiktok/tiktok-connection";
import { PageHeader } from "@/components/app/page-header";
import { ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { Dialog } from "@/components/ui/dialog";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { analyticsOutcome } from "@/lib/performance";
import {
  connectionOutcome,
  disconnectYouTube,
  getYouTubeStatus,
  isGoogleConsentUrl,
  startYouTubeConnection,
  forgetReturnPath,
  peekReturnPath,
} from "@/lib/publishing";
import { useApi } from "@/lib/use-api";

const noSubscription = () => () => {};

/** Account settings: the YouTube connection used for publishing. */
export function SettingsView() {
  const params = useSearchParams();
  const router = useRouter();
  const outcome = useMemo(() => {
    const query = new URLSearchParams(params.toString());
    const youtube = connectionOutcome(query);
    if (youtube) return { ...youtube, title: youtube.ok ? "Connected" : "Not connected" };
    return analyticsOutcome(query);
  }, [params]);
  const { data, error, loading, reload } = useApi(getYouTubeStatus);
  // Connected from a Short or the editor: go back there. A failure stays here, with a way back.
  const stored = useSyncExternalStore(noSubscription, peekReturnPath, () => null);
  const back = params.get("youtube") !== null ? stored : null;
  useEffect(() => {
    if (back && params.get("youtube") === "connected") {
      forgetReturnPath();
      router.replace(back);
    }
  }, [back, params, router]);
  const [busy, setBusy] = useState<"connect" | "disconnect" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  async function connect() {
    setBusy("connect");
    setActionError(null);
    try {
      const { authorization_url } = await startYouTubeConnection();
      if (!isGoogleConsentUrl(authorization_url)) throw new Error("Unexpected sign-in address.");
      window.location.assign(authorization_url); // Google sends the browser back here
    } catch (failure) {
      setActionError(errorMessage(failure));
      setBusy(null);
    }
  }

  async function disconnect() {
    setConfirming(false);
    setBusy("disconnect");
    setActionError(null);
    try {
      const result = await disconnectYouTube();
      setNotice(
        result.revoked_with_provider
          ? "Disconnected. PeakSift's access was also removed from your Google account."
          : "Disconnected here. Google could not be reached to remove access; you can remove PeakSift in your Google account's third-party access settings.",
      );
      router.replace("/settings");
      reload();
    } catch (failure) {
      setActionError(errorMessage(failure));
    } finally {
      setBusy(null);
    }
  }

  const connection = data?.connection ?? null;
  return (
    <>
      <PageHeader title="Settings" description="Accounts PeakSift can publish to." />
      <Dialog
        open={confirming}
        onClose={() => setConfirming(false)}
        title="Disconnect YouTube?"
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirming(false)} data-autofocus>
              Keep connected
            </Button>
            <Button variant="danger" onClick={() => void disconnect()}>
              Disconnect
            </Button>
          </>
        }
      >
        <p className="text-sm text-pretty text-muted">
          PeakSift will stop publishing to this channel and remove its access. Shorts already on YouTube stay there, and
          you can connect again at any time.
        </p>
      </Dialog>
      <Panel
        id="youtube"
        title={
          <span className="inline-flex items-center gap-2">
            <CirclePlay aria-hidden="true" className="size-4 text-red-400" />
            YouTube
          </span>
        }
        description="Publish finished shorts to your channel. Publishing asks only for permission to upload videos — it cannot read, change or delete anything on your channel. Analytics is a separate, optional, read-only permission."
      >
        <div className="space-y-4">
          {outcome ? (
            <InlineAlert
              tone={outcome.ok ? "info" : "warning"}
              title={outcome.title}
              action={back ? <ButtonLink href={back} variant="secondary">Back to your Short</ButtonLink> : undefined}
            >
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
          ) : !data.enabled ? (
            <InlineAlert tone="info" title="Publishing is not enabled on this server">
              The server operator has not configured YouTube publishing. Download your shorts and upload them yourself in the meantime.
            </InlineAlert>
          ) : connection ? (
            <div className="flex flex-col gap-4 rounded-xl border border-border bg-surface-2 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0 text-sm">
                <p className="flex items-center gap-2 font-medium text-foreground">
                  {connection.status === "connected" ? (
                    <CheckCircle2 aria-hidden="true" className="size-4 text-emerald-300" />
                  ) : (
                    <Unplug aria-hidden="true" className="size-4 text-warning" />
                  )}
                  {connection.account_title || "YouTube account connected"}
                </p>
                <p className="mt-0.5 text-muted">
                  {connection.status === "connected"
                    ? `Connected ${formatDate(connection.connected_at)}.${connection.account_title ? "" : " The channel name appears after your first upload."}`
                    : "Google no longer accepts this connection (access was removed or expired). Reconnect to publish again."}
                </p>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                {connection.status !== "connected" ? (
                  <Button onClick={connect} disabled={busy !== null}>
                    {busy === "connect" ? "Opening Google…" : "Reconnect"}
                  </Button>
                ) : null}
                <Button variant="secondary" onClick={() => setConfirming(true)} disabled={busy !== null}>
                  {busy === "disconnect" ? "Disconnecting…" : "Disconnect"}
                </Button>
              </div>
            </div>
          ) : null}
          {data?.enabled && data.analytics_enabled && connection?.status === "connected" ? (
            <div id="analytics" className="space-y-3 rounded-xl border border-border px-4 py-4">
              <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                <p className="font-medium text-foreground">Analytics access</p>
                <p className={`text-sm ${connection.analytics_access ? "text-emerald-300" : "text-muted"}`}>
                  {connection.analytics_access ? "Connected (read-only)" : "Not connected"}
                </p>
              </div>
              {connection.analytics_access ? (
                <>
                  <p className="text-sm text-muted">
                    PeakSift reads metrics for the shorts you published from here. Disconnect YouTube above to remove both permissions.
                  </p>
                  <DeleteCollectedMetrics />
                </>
              ) : (
                <>
                  <AnalyticsPermissionNote />
                  <ConnectAnalyticsButton />
                </>
              )}
            </div>
          ) : null}
          {!loading && !error && data?.enabled && !connection ? (
            <div className="flex flex-col gap-3 rounded-xl border border-dashed border-border px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-muted">No YouTube account is connected.</p>
              <Button onClick={connect} disabled={busy !== null}>
                <CirclePlay aria-hidden="true" />
                {busy === "connect" ? "Opening Google…" : "Connect YouTube"}
              </Button>
            </div>
          ) : null}
        </div>
      </Panel>
      <div className="mt-6">
        <TikTokConnection />
      </div>
    </>
  );
}

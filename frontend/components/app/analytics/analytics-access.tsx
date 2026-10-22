"use client";

import { BarChart3, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { InlineAlert } from "@/components/ui/inline-alert";
import { errorMessage } from "@/lib/api";
import {
  accessState,
  deleteCollectedMetrics,
  startAnalyticsConnection,
  type AnalyticsAccess,
} from "@/lib/performance";
import { isGoogleConsentUrl } from "@/lib/publishing";

/** Starts the explicit, read-only analytics upgrade in Google's consent screen. */
export function ConnectAnalyticsButton({ label = "Connect analytics (read-only)" }: { label?: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      const { authorization_url } = await startAnalyticsConnection();
      if (!isGoogleConsentUrl(authorization_url)) throw new Error("Unexpected sign-in address.");
      window.location.assign(authorization_url); // Google sends the browser back to /settings
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <Button onClick={connect} disabled={busy}>
        <BarChart3 aria-hidden="true" />
        {busy ? "Opening Google…" : label}
      </Button>
      {error ? <InlineAlert title="That did not work">{error}</InlineAlert> : null}
    </div>
  );
}

/** What analytics access means, in plain words: read-only, opt-in, separate from publishing. */
export function AnalyticsPermissionNote() {
  return (
    <ul className="space-y-1.5 text-sm text-muted">
      <li className="flex gap-2">
        <ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-emerald-300" />
        Read-only: PeakSift can view your channel&apos;s videos and YouTube Analytics. It cannot change, delete or post anything.
      </li>
      <li className="flex gap-2">
        <ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-emerald-300" />
        Only shorts you published from PeakSift are tracked; other videos on your channel are never synced.
      </li>
      <li className="flex gap-2">
        <ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-emerald-300" />
        Publishing keeps working whatever you choose. Disconnecting YouTube in Settings removes both.
      </li>
    </ul>
  );
}

/** Everything a creator sees before analytics is ready, per access state. */
export function AnalyticsAccessGate({ access }: { access: AnalyticsAccess }) {
  const state = accessState(access);
  if (state === "disabled") {
    return (
      <InlineAlert tone="info" title="Analytics is not enabled on this server">
        The server operator has not turned on performance analytics. Your shorts and publishing are unaffected.
      </InlineAlert>
    );
  }
  if (state === "not_connected" || state === "reconnect") {
    return (
      <InlineAlert
        tone="info"
        title={state === "reconnect" ? "Reconnect YouTube first" : "Connect YouTube first"}
        action={<ButtonLink href="/settings" variant="secondary" size="sm">Open settings</ButtonLink>}
      >
        Analytics uses your YouTube connection. {state === "reconnect" ? "Google no longer accepts it." : "No account is connected yet."}
      </InlineAlert>
    );
  }
  return (
    <div className="space-y-4 rounded-xl border border-border bg-surface-2 px-4 py-4">
      <div>
        <p className="font-medium text-foreground">Analytics access not connected</p>
        <p className="mt-0.5 text-sm text-muted">
          Your connection can upload videos only. To see how your published shorts are doing, grant read-only access to your YouTube analytics.
        </p>
      </div>
      <AnalyticsPermissionNote />
      <ConnectAnalyticsButton />
    </div>
  );
}

/** Delete what PeakSift collected, after an explicit second confirmation. */
export function DeleteCollectedMetrics() {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      const deleted = await deleteCollectedMetrics();
      setResult(
        `Deleted ${deleted.days} daily records and ${deleted.snapshots} counter readings. Syncing stops until you refresh a short or connect analytics again.`,
      );
      setConfirming(false);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      {confirming ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <p className="text-sm text-muted">Delete every metric and pattern PeakSift collected? This cannot be undone.</p>
          <div className="flex gap-2">
            <Button variant="danger" size="sm" onClick={remove} disabled={busy}>
              {busy ? "Deleting…" : "Delete metrics"}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirming(false)} disabled={busy}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Button variant="secondary" size="sm" onClick={() => setConfirming(true)}>
          Delete collected metrics
        </Button>
      )}
      {result ? <p className="text-xs text-muted">{result}</p> : null}
      {error ? <InlineAlert title="That did not work">{error}</InlineAlert> : null}
    </div>
  );
}

"use client";

import { type FormEvent, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { inputClasses } from "@/components/ui/input-styles";
import { InlineAlert } from "@/components/ui/inline-alert";
import { selectClasses } from "@/components/ui/select-styles";
import { errorMessage } from "@/lib/api";
import { type AssetLabels, labelChanges, labelProblem, labelsOf } from "@/lib/asset-labels";
import { getMarkets } from "@/lib/markets";
import { useApi } from "@/lib/use-api";

/**
 * Where an asset comes from and whether it is local to a market (V1.8). Everything here is the
 * creator's choice: PeakSift never guesses a place or a licence from what an asset shows.
 */
export function AssetLabelsForm({
  family,
  asset,
  onSave,
}: {
  family: "visual" | "audio";
  asset: Partial<AssetLabels>;
  onSave: (changes: Partial<AssetLabels>) => Promise<void>;
}) {
  const id = useId();
  const { data: vocab } = useApi(getMarkets);
  const saved = labelsOf(asset);
  const [labels, setLabels] = useState<AssetLabels>(saved);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const changes = labelChanges(saved, labels);
  const problem = labelProblem(labels);
  const local = vocab?.markets.find((m) => m.code === labels.market && m.local_label);
  const categories = family === "visual" ? vocab?.visual_categories : vocab?.audio_categories;
  const set = (patch: Partial<AssetLabels>) => {
    setLabels((current) => ({ ...current, ...patch }));
    setState("idle");
  };

  async function save(event: FormEvent) {
    event.preventDefault();
    if (problem || !Object.keys(changes).length) return;
    setState("saving");
    setError(null);
    try {
      await onSave(changes);
      setState("saved");
    } catch (failure) {
      setError(errorMessage(failure));
      setState("idle");
    }
  }

  if (!vocab) return null;
  return (
    <form onSubmit={save} className="space-y-3 rounded-xl border border-border p-3">
      <p className="text-small font-medium text-foreground">Source and market</p>
      <p className="text-xs text-muted">Only use media you made, own or have a licence for. Local assets come first in that market&apos;s searches; Global ones stay available everywhere.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <label htmlFor={`${id}-origin`} className="text-xs font-medium text-muted">Where it comes from</label>
          <select id={`${id}-origin`} value={labels.origin} onChange={(e) => set({ origin: e.target.value })} className={selectClasses}>
            {vocab.asset_origins.map((o) => (
              <option key={o.code} value={o.code}>{o.label}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label htmlFor={`${id}-market`} className="text-xs font-medium text-muted">Market</label>
          <select id={`${id}-market`} value={labels.market} onChange={(e) => set({ market: e.target.value, location: null })} className={selectClasses}>
            {vocab.markets.map((m) => (
              <option key={m.code} value={m.code}>{m.local_label ? `${m.local_label} (${m.name})` : m.name}</option>
            ))}
          </select>
        </div>
        {labels.origin === "licensed" || labels.license_note ? (
          <div className="space-y-1 sm:col-span-2">
            <label htmlFor={`${id}-licence`} className="text-xs font-medium text-muted">
              Licence or source {labels.origin === "licensed" ? "(required)" : "(optional)"}
            </label>
            <input id={`${id}-licence`} value={labels.license_note ?? ""} maxLength={300} onChange={(e) => set({ license_note: e.target.value })} placeholder="e.g. licence name and number, or the seller" className={inputClasses} />
          </div>
        ) : null}
        <div className="space-y-1">
          <label htmlFor={`${id}-category`} className="text-xs font-medium text-muted">Category</label>
          <select id={`${id}-category`} value={labels.category ?? ""} onChange={(e) => set({ category: e.target.value || null })} className={selectClasses}>
            <option value="">None</option>
            {(categories ?? []).map((c) => (
              <option key={c.code} value={c.code}>{c.label}</option>
            ))}
          </select>
        </div>
        {local && family === "visual" ? (
          <div className="space-y-1">
            <label htmlFor={`${id}-location`} className="text-xs font-medium text-muted">Location (only if you know it)</label>
            <select id={`${id}-location`} value={labels.location ?? ""} onChange={(e) => set({ location: e.target.value || null })} className={selectClasses}>
              <option value="">Not set</option>
              {local.locations.map((place) => (
                <option key={place} value={place}>{place}</option>
              ))}
            </select>
          </div>
        ) : null}
      </div>
      {problem ? <p className="text-xs text-amber-200">{problem}</p> : null}
      {error ? <InlineAlert title="The labels could not be saved">{error}</InlineAlert> : null}
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" variant="secondary" disabled={!Object.keys(changes).length || Boolean(problem) || state === "saving"}>
          {state === "saving" ? "Saving…" : "Save labels"}
        </Button>
        {state === "saved" && !Object.keys(changes).length ? <span role="status" className="text-xs text-emerald-300">Saved</span> : null}
      </div>
    </form>
  );
}

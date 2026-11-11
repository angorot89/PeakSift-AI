"use client";

import { Languages } from "lucide-react";
import { useCallback, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { selectClasses } from "@/components/ui/select-styles";
import { errorMessage } from "@/lib/api";
import { getMarkets, getProjectLanguage } from "@/lib/markets";
import { type Project, updateProject } from "@/lib/projects";
import { useApi } from "@/lib/use-api";

/** The project's market and language: two separate, explicit choices. Shorts already made keep
 * the market they were made with; detection is a hedged hint ("Likely Darija"), never a verdict. */
export function ProjectMarketControl({ project, onChange }: { project: Project; onChange: (project: Project) => void }) {
  const id = useId();
  const { data: vocab } = useApi(getMarkets);
  const loadLanguage = useCallback(() => getProjectLanguage(project.id), [project.id]);
  const { data: detected } = useApi(loadLanguage);
  const [market, setMarket] = useState(project.market);
  const [language, setLanguage] = useState(project.content_language);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const changed = market !== project.market || language !== project.content_language;
  if (!vocab) return null;
  async function save() {
    setState("saving");
    setError(null);
    try {
      onChange(await updateProject(project.id, { market, content_language: language }));
      setState("saved");
    } catch (failure) {
      setError(errorMessage(failure));
      setState("idle");
    }
  }
  return (
    <Card>
      <div className="flex items-center gap-2">
        <Languages aria-hidden="true" className="size-4 text-accent-soft" />
        <h2 className="text-title">Market and language</h2>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <label htmlFor={`${id}-market`} className="text-xs font-medium text-muted">Made for</label>
          <select id={`${id}-market`} value={market} onChange={(e) => { setMarket(e.target.value); setState("idle"); }} className={selectClasses}>
            {vocab.markets.map((m) => (
              <option key={m.code} value={m.code}>{m.code === "global" ? "Global" : `${m.name} Mode`}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label htmlFor={`${id}-language`} className="text-xs font-medium text-muted">Language of your videos</label>
          <select id={`${id}-language`} value={language} onChange={(e) => { setLanguage(e.target.value); setState("idle"); }} className={selectClasses}>
            {vocab.content_languages.map((l) => (
              <option key={l.code} value={l.code}>{l.label}</option>
            ))}
          </select>
        </div>
      </div>
      {detected && detected.detected.language !== "unknown" ? (
        <p className="mt-2 text-xs text-muted">From your transcript: {detected.detected.label}. Your choice always wins.</p>
      ) : null}
      <p className="mt-1 text-xs text-subtle">Shorts you already made keep the market they were made with.</p>
      {error ? <p role="alert" className="mt-2 text-xs text-rose-300">{error}</p> : null}
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" variant="secondary" disabled={!changed || state === "saving"} onClick={() => void save()}>
          {state === "saving" ? "Saving…" : "Save"}
        </Button>
        {state === "saved" && !changed ? <span role="status" className="text-xs text-emerald-300">Saved</span> : null}
      </div>
    </Card>
  );
}

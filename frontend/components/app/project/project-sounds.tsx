"use client";

import { Music } from "lucide-react";
import { useCallback, useState } from "react";
import { AssetLabelsForm } from "@/components/app/asset-labels-form";
import { SectionHeader } from "@/components/ui/section-header";
import { listAudio, updateAudio, type AudioAsset } from "@/lib/audio";
import { useApi } from "@/lib/use-api";

/** The project's sounds and their labels (where they come from, local market, category). Sounds
 * are uploaded in the editor's Sound tool; PeakSift never adds music or sounds itself. */
export function ProjectSounds({ projectId }: { projectId: string }) {
  const load = useCallback(() => listAudio(projectId), [projectId]);
  const { data } = useApi(load);
  const [updated, setUpdated] = useState<Record<string, AudioAsset>>({});
  if (!data?.length) return null;
  return (
    <section aria-labelledby="project-sounds-heading" className="space-y-3">
      <SectionHeader id="project-sounds-heading" title="Sounds" description="Music and effects you uploaded in the editor. Label where each comes from and whether it's local." />
      <ul className="space-y-2">
        {data.map((sound) => {
          const current = updated[sound.id] ?? sound;
          return (
            <li key={sound.id}>
              <details className="rounded-block border border-border bg-surface px-4 py-2">
                <summary className="flex min-h-11 cursor-pointer items-center gap-2 text-sm">
                  <Music aria-hidden="true" className="size-4 text-subtle" />
                  <span dir="auto" className="truncate font-medium text-foreground">{current.display_name}</span>
                  <span className="text-caption text-subtle">
                    {current.kind === "music" ? "Music" : "Effect"} · {current.duration_seconds.toFixed(1)} s
                    {current.market && current.market !== "global" ? " · Moroccan" : ""}
                  </span>
                </summary>
                <div className="pt-2 pb-2">
                  <AssetLabelsForm
                    family="audio"
                    asset={current}
                    onSave={async (changes) => {
                      const saved = await updateAudio(projectId, sound.id, changes);
                      setUpdated((map) => ({ ...map, [sound.id]: saved }));
                    }}
                  />
                </div>
              </details>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

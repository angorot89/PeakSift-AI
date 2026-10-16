"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { FormError } from "@/components/ui/form-error";
import { Panel } from "@/components/ui/panel";
import { errorMessage } from "@/lib/api";
import { deleteProject, type Project } from "@/lib/projects";

/** Permanent deletion of a project and every file in it, confirmed by typing its name. */
export function DeleteProject({ project }: { project: Project }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const matches = typed === project.name;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!matches || busy) return;
    setBusy(true);
    setError(null);
    try {
      await deleteProject(project.id, typed);
      router.replace("/projects");
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  return (
    <Panel
      id="delete-project"
      title="Delete project"
      description="Permanently removes the project, its videos, transcripts, clips, edits and audio, including every media file. This cannot be undone."
      className="mt-8 border-rose-500/30"
    >
      {open ? (
        <form onSubmit={submit} className="space-y-4">
          <Field
            id="confirm-project-name"
            label={`Type “${project.name}” to confirm`}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            disabled={busy}
          />
          <FormError>{error}</FormError>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="danger" disabled={!matches || busy}>
              {busy ? "Deleting…" : "Delete permanently"}
            </Button>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => {
                setOpen(false);
                setTyped("");
                setError(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <Button variant="danger" onClick={() => setOpen(true)}>
          Delete project…
        </Button>
      )}
    </Panel>
  );
}

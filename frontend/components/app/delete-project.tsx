"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { FormError } from "@/components/ui/form-error";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api";
import { deleteProject, type Project } from "@/lib/projects";

/** Permanent deletion of a project and every file in it, confirmed by typing its name. */
export function DeleteProjectDialog({ project, open, onClose }: { project: Project; open: boolean; onClose: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const formId = useId();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const matches = typed === project.name;

  function close() {
    if (busy) return;
    setTyped("");
    setError(null);
    onClose();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!matches || busy) return;
    setBusy(true);
    setError(null);
    try {
      await deleteProject(project.id, typed);
      toast(`“${project.name}” was deleted`);
      router.replace("/projects");
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Delete this project?"
      description="This permanently removes the project, its videos, transcripts, clips, shorts, audio and visual assets, including every media file. It cannot be undone. Shorts already on YouTube stay there."
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="danger" disabled={!matches || busy}>
            {busy ? "Deleting…" : "Delete permanently"}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} className="space-y-4">
        <Field
          id="confirm-project-name"
          label={`Type “${project.name}” to confirm`}
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          data-autofocus
          disabled={busy}
        />
        <FormError>{error}</FormError>
      </form>
    </Dialog>
  );
}

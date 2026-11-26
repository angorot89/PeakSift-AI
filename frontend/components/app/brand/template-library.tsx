"use client";

import { Copy, MoreHorizontal, Pencil, Plus, Shapes, Star, Trash2, Type } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { cardClasses } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Menu } from "@/components/ui/menu";
import { SectionHeader } from "@/components/ui/section-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api";
import { deleteTemplate, duplicateTemplate, listTemplates, updateTemplate, type Template } from "@/lib/brand";
import { RECIPE_LABELS, summary } from "@/lib/template-rules";

function updated(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** The creator's Short templates: the default first, then the most recently changed. */
export function TemplateLibrary() {
  const toast = useToast();
  const router = useRouter();
  const [items, setItems] = useState<Template[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<Template | null>(null);
  const [newName, setNewName] = useState("");
  const [deleting, setDeleting] = useState<Template | null>(null);

  const load = useCallback(() => {
    listTemplates()
      .then(setItems)
      .catch((failure: unknown) => setError(errorMessage(failure)));
  }, []);
  useEffect(load, [load]);

  async function act(task: () => Promise<unknown>, done: string) {
    setError(null);
    try {
      await task();
      toast(done);
      load();
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }

  return (
    <section aria-labelledby="templates-heading">
      <SectionHeader
        id="templates-heading"
        title="Your templates"
        description="How your Shorts are edited. Your default template is where every new Short starts."
        actions={
          items && items.length > 0 ? (
            <ButtonLink href="/brand/templates/new" variant="secondary" size="sm">
              <Plus aria-hidden="true" className="size-4" /> New template
            </ButtonLink>
          ) : null
        }
      />
      {error ? <InlineAlert title="That didn't work">{error}</InlineAlert> : null}
      {items === null && !error ? <Skeleton className="h-40 rounded-card" /> : null}
      {items !== null && items.length === 0 ? (
        <EmptyState
          icon={Shapes}
          title="No templates yet"
          description="Save the styles you use repeatedly so every Short starts closer to finished."
          action={<ButtonLink href="/brand/templates/new">Create one</ButtonLink>}
        />
      ) : null}
      {items && items.length > 0 ? (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((t) => (
            <li key={t.id} className={`${cardClasses({ padding: "md" })} flex min-w-0 flex-col gap-3`}>
              <div className="flex items-start gap-3">
                <span aria-hidden="true" className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-control" style={{ backgroundColor: t.brand?.primary_color ?? "#27272A" }}>
                  <Type className="size-4 text-white/90" />
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="truncate text-title text-foreground">
                    <Link href={`/brand/templates/${t.id}`} className="rounded hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center">
                      {t.name}
                    </Link>
                  </h3>
                  <p className="text-caption text-muted">
                    {t.brand ? t.brand.name : "No brand"}
                    {t.recipe ? ` · ${RECIPE_LABELS[t.recipe]} style` : ""} · updated {updated(t.updated_at)}
                  </p>
                </div>
                <Menu
                  label={`Actions for ${t.name}`}
                  trigger={<MoreHorizontal aria-hidden="true" className="size-4" />}
                  items={[
                    { label: "Edit", icon: Pencil, onSelect: () => router.push(`/brand/templates/${t.id}`) },
                    ...(t.is_default ? [] : [{ label: "Use for new Shorts", icon: Star, onSelect: () => void act(() => updateTemplate(t.id, { is_default: true }), `New Shorts start from “${t.name}”`) }]),
                    { label: "Duplicate", icon: Copy, onSelect: () => void act(() => duplicateTemplate(t.id), "Template duplicated") },
                    { label: "Rename", icon: Type, onSelect: () => { setRenaming(t); setNewName(t.name); } },
                    { label: "Delete", icon: Trash2, tone: "danger", onSelect: () => setDeleting(t) },
                  ]}
                />
              </div>
              {t.is_default ? (
                <p className="inline-flex w-fit items-center gap-1 rounded-full bg-accent/[0.12] px-2 py-0.5 text-caption font-medium text-accent-soft">
                  <Star aria-hidden="true" className="size-3" /> Default
                </p>
              ) : null}
              <p className="text-small text-muted">{summary(t.config, Boolean(t.brand?.has_logo))}</p>
              {t.description ? <p className="line-clamp-2 text-small text-subtle">{t.description}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}

      <Dialog
        open={renaming !== null}
        onClose={() => setRenaming(null)}
        title="Rename template"
        footer={
          <>
            <Button variant="secondary" onClick={() => setRenaming(null)}>
              Cancel
            </Button>
            <Button
              disabled={!newName.trim()}
              onClick={() => {
                const target = renaming!;
                setRenaming(null);
                void act(() => updateTemplate(target.id, { name: newName.trim() }), "Template renamed");
              }}
            >
              Rename
            </Button>
          </>
        }
      >
        <Field id="rename-template" label="Name" value={newName} maxLength={60} data-autofocus onChange={(e) => setNewName(e.target.value)} />
      </Dialog>
      <Dialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title={`Delete “${deleting?.name ?? ""}”?`}
        description="Shorts and plans made with it keep their settings."
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleting(null)}>
              Keep it
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                const target = deleting!;
                setDeleting(null);
                void act(() => deleteTemplate(target.id), "Template deleted");
              }}
            >
              Delete template
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">This can&apos;t be undone.</p>
      </Dialog>
    </section>
  );
}

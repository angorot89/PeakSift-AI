"use client";

import { Check, ImageOff } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api";
import { listLogoCandidates, logoThumbnailUrl, type BrandLogo } from "@/lib/brand";

/**
 * Choose the brand logo from the creator's own images (any project) — the private visual
 * library, no separate upload. A radio group: arrow keys move, the choice is announced, and
 * the selected image is marked by a check and text, not by colour alone.
 */
export function LogoPicker({
  open,
  onClose,
  selected,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  selected: string | null;
  onSelect: (logo: BrandLogo | null) => void;
}) {
  const [items, setItems] = useState<BrandLogo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    listLogoCandidates()
      .then((list) => !cancelled && setItems(list))
      .catch((failure: unknown) => !cancelled && setError(errorMessage(failure)));
    return () => {
      cancelled = true;
    };
  }, [open]);

  const options: (BrandLogo | null)[] = [null, ...(items ?? [])];

  function move(index: number) {
    const next = options[(index + options.length) % options.length];
    onSelect(next);
    window.setTimeout(() => document.getElementById(`logo-option-${next?.id ?? "none"}`)?.focus(), 0);
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Choose a logo"
      description="Pick one of your images. Transparent PNGs look best; logos are never stretched."
      width="40rem"
      footer={<Button onClick={onClose}>Done</Button>}
    >
      {error ? <InlineAlert title="Your images couldn't be loaded">{error}</InlineAlert> : null}
      {items === null && !error ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="aspect-square rounded-block" />
          ))}
        </div>
      ) : null}
      {items !== null ? (
        <>
          <div role="radiogroup" aria-label="Logo" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {options.map((logo, index) => {
              const id = logo?.id ?? null;
              const checked = selected === id;
              return (
                <button
                  key={id ?? "none"}
                  id={`logo-option-${id ?? "none"}`}
                  type="button"
                  role="radio"
                  aria-checked={checked}
                  tabIndex={checked || (selected === null && index === 0) ? 0 : -1}
                  onClick={() => onSelect(logo)}
                  onKeyDown={(event) => {
                    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
                      event.preventDefault();
                      move(index + 1);
                    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
                      event.preventDefault();
                      move(index - 1);
                    }
                  }}
                  className={`relative flex flex-col overflow-hidden rounded-block border text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                    checked ? "border-accent bg-accent/[0.08]" : "border-border hover:border-border-strong"
                  }`}
                >
                  <span className="flex aspect-square items-center justify-center bg-[repeating-conic-gradient(#2a2d33_0_25%,#1f2227_0_50%)] bg-[length:16px_16px]">
                    {logo ? (
                      logo.has_thumbnail ? (
                        // eslint-disable-next-line @next/next/no-img-element -- a private, session-served image
                        <img src={logoThumbnailUrl(logo)} alt="" className="max-h-[80%] max-w-[80%] object-contain" />
                      ) : (
                        <span className="text-caption text-subtle">No preview</span>
                      )
                    ) : (
                      <ImageOff aria-hidden="true" className="size-6 text-subtle" />
                    )}
                  </span>
                  <span className="flex min-h-11 items-center gap-1.5 px-2.5 py-1.5">
                    {checked ? <Check aria-hidden="true" className="size-4 shrink-0 text-accent-soft" /> : null}
                    <span className="min-w-0">
                      <span className="block truncate text-small text-foreground">{logo ? logo.name : "No logo"}</span>
                      {logo ? (
                        <span className="block truncate text-caption text-muted">
                          {logo.project_name}
                          {logo.transparent ? " · transparent" : ""}
                        </span>
                      ) : null}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
          {items.length === 0 ? (
            <p className="mt-4 text-sm text-muted">
              You have no images yet. Upload your logo in a project&apos;s{" "}
              <Link href="/projects" className="text-foreground underline underline-offset-2">
                Assets
              </Link>
              , then choose it here.
            </p>
          ) : (
            <p className="mt-4 text-caption text-muted">Add another image in any project&apos;s Assets to see it here.</p>
          )}
        </>
      ) : null}
    </Dialog>
  );
}

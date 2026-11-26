"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/app/page-header";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { buttonClasses } from "@/components/ui/button-styles";
import { Field } from "@/components/ui/field";
import { FormError } from "@/components/ui/form-error";
import { ApiError, errorMessage } from "@/lib/api";
import { PROJECT_NAME_MAX_LENGTH, createProject } from "@/lib/projects";

export function NewProjectForm() {
  const router = useRouter();
  const { user, setUser } = useAuth();
  const params = useSearchParams();
  const [name, setName] = useState("");
  // Preselected from ?market= (Morocco Mode's button) or the creator's default; always changeable.
  const [market, setMarket] = useState(params.get("market") === "ma" || user?.default_market === "ma" ? "ma" : "global");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setFieldError("Enter a project name.");
      return;
    }
    if (trimmed.length > PROJECT_NAME_MAX_LENGTH) {
      setFieldError(`Use at most ${PROJECT_NAME_MAX_LENGTH} characters.`);
      return;
    }

    setFieldError(null);
    setError(null);
    setSubmitting(true);
    try {
      const project = await createProject(trimmed, market);
      router.push(`/projects/${project.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setUser(null);
      setError(errorMessage(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader
        back={{ href: "/projects", label: "Projects" }}
        title="New project"
        description="Name the recording you want to clip, then upload its source video on the next page."
      />
      <form onSubmit={handleSubmit} noValidate className="space-y-5 rounded-card border border-border bg-surface p-5 sm:p-6">
        <Field
          id="name"
          label="Project name"
          placeholder="Friday stream — September 28"
          autoComplete="off"
          autoFocus
          required
          maxLength={PROJECT_NAME_MAX_LENGTH}
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={fieldError}
        />
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Made for</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {[
              { value: "global", label: "Global", hint: "Every Global tool and library" },
              { value: "ma", label: "Morocco Mode", hint: "Global plus Moroccan context" },
            ].map((option) => (
              <label
                key={option.value}
                className="flex min-h-11 cursor-pointer items-start gap-2 rounded-control border border-border px-3 py-2.5 text-sm has-[:checked]:border-accent/60 has-[:checked]:bg-accent/10"
              >
                <input
                  type="radio"
                  name="market"
                  value={option.value}
                  checked={market === option.value}
                  onChange={() => setMarket(option.value)}
                  className="mt-0.5 accent-[var(--color-accent)]"
                />
                <span>
                  <span className="block font-medium">{option.label}</span>
                  <span className="block text-xs text-muted">{option.hint}</span>
                </span>
              </label>
            ))}
          </div>
          <p className="text-xs text-muted">You can change it later. The language of your videos is a separate choice.</p>
        </fieldset>
        <FormError>{error}</FormError>
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Link
            href="/projects"
            className={buttonClasses("ghost")}
          >
            Cancel
          </Link>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Creating…" : "Create project"}
          </Button>
        </div>
      </form>
    </div>
  );
}

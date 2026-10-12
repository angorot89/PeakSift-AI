"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/app/page-header";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { FormError } from "@/components/ui/form-error";
import { ApiError, errorMessage } from "@/lib/api";
import { PROJECT_NAME_MAX_LENGTH, createProject } from "@/lib/projects";

export function NewProjectForm() {
  const router = useRouter();
  const { setUser } = useAuth();
  const [name, setName] = useState("");
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
      const project = await createProject(trimmed);
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
        eyebrow={
          <Link href="/projects" className="hover:text-foreground">
            ← Projects
          </Link>
        }
        title="New project"
        description="Name the recording you want to clip, then upload its source video on the next page."
      />
      <form onSubmit={handleSubmit} noValidate className="space-y-5">
        <Field
          id="name"
          label="Project name"
          placeholder="Kai Cenat Stream — September 28"
          autoComplete="off"
          autoFocus
          required
          maxLength={PROJECT_NAME_MAX_LENGTH}
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={fieldError}
        />
        <FormError>{error}</FormError>
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Link
            href="/projects"
            className="inline-flex h-9 items-center justify-center rounded-full px-4 text-sm text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
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

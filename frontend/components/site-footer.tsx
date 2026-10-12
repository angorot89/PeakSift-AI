import { Logo } from "@/components/logo";

export function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-4 px-6 py-10 sm:flex-row sm:items-center">
        <Logo />
        <p className="text-sm text-muted">Find the moments worth clipping.</p>
      </div>
    </footer>
  );
}

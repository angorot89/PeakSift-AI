import Link from "next/link";
import { Logo } from "@/components/logo";

const COLUMNS: { title: string; links: { href: string; label: string }[] }[] = [
  {
    title: "Product",
    links: [
      { href: "/features/ai-moments", label: "AI moments" },
      { href: "/features/find-clips", label: "Find Clips" },
      { href: "/features/auto-edit", label: "Auto Edit" },
      { href: "/features/smart-reframe", label: "Smart reframe" },
      { href: "/features/captions", label: "Dynamic captions" },
      { href: "/features/publish", label: "Schedule & publish" },
      { href: "/features", label: "All tools" },
    ],
  },
  {
    title: "Made for",
    links: [
      { href: "/made-for/podcasters", label: "Podcasters" },
      { href: "/made-for/streamers", label: "Streamers" },
      { href: "/made-for/educators", label: "Educators & coaches" },
      { href: "/made-for/interviews", label: "Interviews & talks" },
      { href: "/features/morocco-mode", label: "Morocco Mode" },
    ],
  },
  {
    title: "Resources",
    links: [
      { href: "/guides", label: "Guides" },
      { href: "/guides/getting-started", label: "Getting started" },
      { href: "/#faq", label: "FAQ" },
    ],
  },
  {
    title: "Company",
    links: [
      { href: "/about", label: "About" },
      { href: "/pricing", label: "Pricing" },
      { href: "/privacy", label: "Your data" },
      { href: "/terms", label: "Terms of Service" },
      { href: "/privacy-policy", label: "Privacy Policy" },
      { href: "/login", label: "Log in" },
      { href: "/register", label: "Create an account" },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="overflow-hidden border-t border-border bg-surface px-6 pt-16">
      <div className="mx-auto grid max-w-6xl gap-10 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr_1fr]">
        <div>
          <Logo />
          <p className="mt-3 max-w-xs text-muted">Find the moments worth clipping.</p>
        </div>
        {COLUMNS.map((column) => (
          <nav key={column.title} aria-label={column.title}>
            <p className="font-display font-bold">{column.title}</p>
            <ul className="mt-3 space-y-1">
              {column.links.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="inline-flex min-h-9 items-center text-muted transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <p className="mx-auto mt-12 max-w-6xl border-t border-border pt-6 text-small text-subtle">
        © PeakSift. Early access.
      </p>
      {/* The name, large and quiet, as the page's last line. */}
      <p
        aria-hidden="true"
        className="mx-auto mt-8 max-w-6xl font-display text-[clamp(4.5rem,19vw,16rem)] leading-[0.8] font-extrabold tracking-[-0.04em] text-surface-3 select-none"
      >
        PeakSift
      </p>
    </footer>
  );
}

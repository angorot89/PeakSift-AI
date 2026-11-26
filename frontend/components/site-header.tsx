import { HeaderAuth } from "@/components/auth/header-auth";
import { Logo } from "@/components/logo";

const navItems = [
  { href: "/#features", label: "Features" },
  { href: "/#toolkit", label: "Toolkit" },
  { href: "/#faq", label: "FAQ" },
];

/** The website's navigation: a floating bar that stays at the top while the page scrolls. */
export function SiteHeader() {
  return (
    <header className="sticky top-0 z-50 px-3 pt-3 sm:px-6">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 rounded-card border border-white/60 bg-white/85 px-4 shadow-[0_8px_30px_-12px_rgb(14_18_34/0.35)] backdrop-blur-xl sm:px-5">
        <Logo />
        <nav aria-label="Main" className="flex items-center gap-6">
          <ul className="hidden items-center gap-6 text-sm font-medium text-muted md:flex">
            {navItems.map((item) => (
              <li key={item.href}>
                <a
                  href={item.href}
                  className="inline-flex min-h-11 items-center rounded-sm transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
                >
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
          <HeaderAuth />
        </nav>
      </div>
    </header>
  );
}

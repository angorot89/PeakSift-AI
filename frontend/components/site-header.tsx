import { Logo } from "@/components/logo";
import { ButtonLink } from "@/components/ui/button-link";

const navItems = [
  { href: "#how-it-works", label: "How it works" },
  { href: "#platform", label: "Platform" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/70 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Logo />
        <nav aria-label="Main" className="flex items-center gap-6">
          <ul className="hidden items-center gap-6 text-sm text-muted sm:flex">
            {navItems.map((item) => (
              <li key={item.href}>
                <a href={item.href} className="transition-colors hover:text-foreground">
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
          <ButtonLink href="#get-started">Get Started</ButtonLink>
        </nav>
      </div>
    </header>
  );
}

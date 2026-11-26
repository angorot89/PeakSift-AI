"use client";

import {
  BarChart3,
  CalendarClock,
  ChevronDown,
  Crop,
  GraduationCap,
  Languages,
  Menu as MenuIcon,
  Mic,
  Gamepad2,
  Palette,
  Presentation,
  Sparkles,
  Wand2,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { HeaderAuth } from "@/components/auth/header-auth";
import { Logo } from "@/components/logo";

type Item = { href: string; title: string; text: string; icon: LucideIcon; tint: string; badge?: string };
type Group = { key: string; label: string; heading: string; items: Item[]; chips?: { href: string; label: string }[] };

const GROUPS: Group[] = [
  {
    key: "product",
    label: "Product",
    heading: "Tools",
    items: [
      { href: "/#find", title: "AI moments", text: "Ranked moments from your long video, with the reason for each", icon: Sparkles, tint: "bg-[#3d5afe]/10 text-[#2f4ae0]", badge: "Popular" },
      { href: "/#edit", title: "Editor", text: "Smart reframe, word-by-word captions, visuals and sound", icon: Crop, tint: "bg-violet-500/10 text-violet-700" },
      { href: "/#edit", title: "Auto Edit", text: "A first cut made for you, ready to tweak", icon: Wand2, tint: "bg-amber-500/15 text-amber-800" },
      { href: "/#publish", title: "Publisher", text: "Post or schedule to YouTube, TikTok and Instagram", icon: CalendarClock, tint: "bg-emerald-500/10 text-emerald-700" },
      { href: "/#learn", title: "Analytics", text: "How every published Short is doing", icon: BarChart3, tint: "bg-sky-500/10 text-sky-700" },
      { href: "/#toolkit", title: "Brand Studio", text: "Your colours, logo and templates on every Short", icon: Palette, tint: "bg-rose-500/10 text-rose-700" },
    ],
    chips: [
      { href: "/#find", label: "Find Clips" },
      { href: "/#edit", label: "Word-by-word captions" },
      { href: "/#edit", label: "Smart reframe" },
      { href: "/#publish", label: "Scheduling" },
      { href: "/#toolkit", label: "Morocco Mode" },
    ],
  },
  {
    key: "made-for",
    label: "Made for",
    heading: "Made for",
    items: [
      { href: "/#made-for", title: "Podcasters", text: "Turn every episode into a week of Shorts", icon: Mic, tint: "bg-[#3d5afe]/10 text-[#2f4ae0]" },
      { href: "/#made-for", title: "Streamers", text: "Clip the best of a long stream while it is still fresh", icon: Gamepad2, tint: "bg-violet-500/10 text-violet-700" },
      { href: "/#made-for", title: "Educators & coaches", text: "Short lessons from long classes and calls", icon: GraduationCap, tint: "bg-amber-500/15 text-amber-800" },
      { href: "/#made-for", title: "Interviews & talks", text: "The quotable moments from every conversation", icon: Presentation, tint: "bg-emerald-500/10 text-emerald-700" },
      { href: "/#toolkit", title: "Moroccan creators", text: "Morocco Mode: Darija-aware hooks and local formats", icon: Languages, tint: "bg-rose-500/10 text-rose-700" },
    ],
  },
];

const LINKS = [{ href: "/#faq", label: "FAQ" }];

/** One tool or audience in a menu: icon tile, title (and badge), one line. */
function MenuCard({ item, onPick }: { item: Item; onPick: () => void }) {
  return (
    <a
      href={item.href}
      onClick={onPick}
      className="group flex gap-3 rounded-block border border-border bg-surface p-3.5 transition-[border-color,box-shadow,transform] duration-150 hover:-translate-y-px hover:border-accent/40 hover:shadow-[0_8px_24px_-14px_rgb(14_18_34/0.4)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <span className={`flex size-10 shrink-0 items-center justify-center rounded-control ${item.tint}`}>
        <item.icon aria-hidden="true" className="size-5" />
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-2 font-semibold text-foreground">
          {item.title}
          {item.badge ? <span className="rounded-full bg-accent/10 px-2 text-caption font-semibold text-accent-soft">{item.badge}</span> : null}
        </span>
        <span className="mt-0.5 block text-small text-muted">{item.text}</span>
      </span>
    </a>
  );
}

/**
 * The website's navigation: a floating bar, see-through over the blue hero and solid once the
 * page scrolls. Product and Made for open wide menus (hover, click or keyboard; Escape closes and
 * returns focus). Phones get one menu button with the same content.
 */
export function SiteHeader() {
  const [open, setOpen] = useState<string | null>(null);
  const [mobile, setMobile] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const closeTimer = useRef<number | null>(null);
  const hoverOpened = useRef(false);
  const buttons = useRef<Record<string, HTMLButtonElement | null>>({});
  const panelId = useId();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!open && !mobile) return;
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (open) buttons.current[open]?.focus();
      setOpen(null);
      setMobile(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, mobile]);

  const cancelClose = () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
  };
  const closeSoon = () => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => {
      hoverOpened.current = false;
      setOpen(null);
    }, 160);
  };
  const close = () => {
    setOpen(null);
    setMobile(false);
  };

  const group = GROUPS.find((g) => g.key === open);
  const solid = scrolled || open !== null || mobile;

  return (
    // The header keeps one height; the bar inside floats, so an open menu covers the page
    // instead of pushing it down.
    <header className="sticky top-0 z-50 h-[4.75rem]">
      <div
        onMouseLeave={closeSoon}
        onMouseEnter={cancelClose}
        className={`absolute inset-x-3 top-3 mx-auto max-w-6xl overflow-hidden rounded-card border transition-[background-color,border-color,box-shadow] duration-300 sm:inset-x-6 ${
          solid
            ? "border-border bg-white shadow-[0_16px_40px_-16px_rgb(14_18_34/0.35)]"
            : "border-white/40 bg-white/15 backdrop-blur-xl"
        }`}
      >
        <div className="flex h-16 items-center justify-between gap-4 px-4 sm:px-5">
          <Logo onDark={!solid} />
          <nav aria-label="Main" className="hidden items-center gap-1 lg:flex">
            {GROUPS.map((g) => (
              <button
                key={g.key}
                ref={(node) => {
                  buttons.current[g.key] = node;
                }}
                type="button"
                aria-expanded={open === g.key}
                aria-controls={panelId}
                onPointerEnter={(event) => {
                  if (event.pointerType !== "mouse") return;
                  cancelClose();
                  hoverOpened.current = true;
                  setOpen(g.key);
                }}
                // A mouse already opened it by hovering, so a click keeps it open; keyboard and
                // touch toggle it.
                onClick={(event) =>
                  setOpen((current) => (event.detail > 0 && current === g.key && hoverOpened.current ? g.key : current === g.key ? null : g.key))
                }
                className={`inline-flex min-h-10 items-center gap-1 rounded-control px-3 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                  solid ? "text-foreground hover:bg-surface-2" : "text-white hover:bg-white/15"
                } ${open === g.key ? "bg-surface-2" : ""}`}
              >
                {g.label}
                <ChevronDown aria-hidden="true" className={`size-4 transition-transform duration-200 ${open === g.key ? "rotate-180" : ""}`} />
              </button>
            ))}
            {LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                onMouseEnter={closeSoon}
                className={`inline-flex min-h-10 items-center rounded-control px-3 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                  solid ? "text-foreground hover:bg-surface-2" : "text-white hover:bg-white/15"
                }`}
              >
                {link.label}
              </a>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <HeaderAuth onDark={!solid} />
            <button
              type="button"
              aria-expanded={mobile}
              aria-label={mobile ? "Close menu" : "Open menu"}
              onClick={() => setMobile((m) => !m)}
              className={`flex size-11 items-center justify-center rounded-control lg:hidden ${solid ? "text-foreground hover:bg-surface-2" : "text-white hover:bg-white/15"}`}
            >
              {mobile ? <X aria-hidden="true" className="size-5" /> : <MenuIcon aria-hidden="true" className="size-5" />}
            </button>
          </div>
        </div>

        {/* The wide menu, inside the same bar so it grows downward with it. */}
        <div id={panelId} hidden={!group} className="border-t border-border px-4 pt-4 pb-5 sm:px-5">
          {group ? (
            <div className="lp-fade" key={group.key}>
              <p className="text-caption font-semibold text-subtle">{group.heading}</p>
              <div className={`mt-3 grid gap-3 ${group.items.length > 5 ? "md:grid-cols-3" : "md:grid-cols-3 xl:grid-cols-5"}`}>
                {group.items.map((item) => (
                  <MenuCard key={item.title} item={item} onPick={close} />
                ))}
              </div>
              {group.chips ? (
                <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4">
                  <span className="mr-1 text-caption font-semibold text-subtle">Popular</span>
                  {group.chips.map((chip) => (
                    <a
                      key={chip.label}
                      href={chip.href}
                      onClick={close}
                      className="inline-flex min-h-8 items-center rounded-control border border-border px-2.5 text-small font-medium text-foreground transition-colors hover:border-accent/40 hover:text-accent-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    >
                      {chip.label}
                    </a>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        {/* Phones and tablets: everything in one panel. */}
        {mobile ? (
          <div className="max-h-[calc(100dvh-6rem)] overflow-y-auto border-t border-border px-4 pt-3 pb-5 lg:hidden">
            {GROUPS.map((g) => (
              <details key={g.key} className="group border-b border-border py-1" open={g.key === "product"}>
                <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between font-semibold [&::-webkit-details-marker]:hidden">
                  {g.label}
                  <ChevronDown aria-hidden="true" className="size-4 text-subtle transition-transform group-open:rotate-180" />
                </summary>
                <div className="grid gap-2 pb-3">
                  {g.items.map((item) => (
                    <MenuCard key={item.title} item={item} onPick={close} />
                  ))}
                </div>
              </details>
            ))}
            {LINKS.map((link) => (
              <a key={link.href} href={link.href} onClick={close} className="flex min-h-12 items-center border-b border-border font-semibold">
                {link.label}
              </a>
            ))}
          </div>
        ) : null}
      </div>
    </header>
  );
}

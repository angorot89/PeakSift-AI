# PeakSift AI — Frontend

Next.js (App Router) + TypeScript + Tailwind CSS. Currently contains the landing page only.

## Structure

```
app/
  layout.tsx       # Root layout: fonts, metadata, global styles
  page.tsx         # Landing page (composes the sections below)
  globals.css      # Tailwind import, theme tokens, base styles
  icon.svg         # Favicon
components/
  landing/         # Landing page sections (hero, preview, how it works, ...)
  ui/              # Small reusable primitives (ButtonLink, SectionHeading)
  logo.tsx
  site-header.tsx
  site-footer.tsx
```

## Run locally

Requires Node.js 20.9+.

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
```

Other scripts:

```bash
npm run lint     # ESLint
npm run build    # Production build
npm run start    # Serve the production build
```

## Known dependency advisories

`npm audit` reports 5 high-severity findings. They are all one advisory, counted once per package in the chain:

- **[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)**: a stack-exhaustion DoS in `braces` (all versions up to 3.0.3, the latest release). No patched version exists.
- **Chain:** `eslint-config-next` (direct, dev) → `@next/eslint-plugin-next` → `fast-glob` → `micromatch` → `braces`. The other four findings are inherited from `braces`.
- **Exposure:** none at runtime. The chain is dev-only (lint-time); `npm ls braces --omit=dev` is empty, and none of it ships in the production build. Exploiting it requires attacker-controlled glob patterns, but ESLint only processes patterns from our own config.
- **Why it's not fixed:** `npm audit fix --force` would downgrade `eslint-config-next` from 16 to 14, which breaks compatibility with Next.js 16. Do not run it.
- **Action:** re-run `npm audit` when `braces` publishes a patched release or when upgrading `eslint-config-next`. A non-breaking fix (`npm update` or an `overrides` entry) should then be possible.

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

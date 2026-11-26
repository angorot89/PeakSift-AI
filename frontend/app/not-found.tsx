import { ArrowLeft, Search } from "lucide-react";
import Link from "next/link";
import { SiteShell } from "@/components/landing/page-blocks";
import { ButtonLink } from "@/components/ui/button-link";

/** Any address that does not exist: say so plainly and offer the ways back. */
export default function NotFound() {
  return (
    <SiteShell>
      <section className="hero-band relative -mt-[4.75rem] px-6 pt-40 pb-28 text-center">
        <p className="font-display text-[clamp(6rem,22vw,12rem)] leading-none font-extrabold tracking-tight text-white/90">404</p>
        <h1 className="mt-4 text-3xl font-extrabold text-white sm:text-4xl">This page doesn&rsquo;t exist</h1>
        <p className="mx-auto mt-3 max-w-md text-lg text-white">The link may be old, or the address mistyped.</p>
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <ButtonLink href="/" size="lg" className="lp-key bg-white !text-[#1b2a8f] hover:!bg-white">
            <ArrowLeft aria-hidden="true" />
            Back to the home page
          </ButtonLink>
          <Link href="/features" className="inline-flex min-h-12 items-center gap-2 px-4 font-semibold text-white hover:underline">
            <Search aria-hidden="true" className="size-4" />
            Browse all tools
          </Link>
        </div>
      </section>
    </SiteShell>
  );
}

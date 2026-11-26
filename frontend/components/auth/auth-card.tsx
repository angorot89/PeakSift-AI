import type { ReactNode } from "react";
import { Logo } from "@/components/logo";
import { MomentStrip } from "@/components/ui/moment-strip";

type AuthCardProps = {
  title: string;
  description: string;
  children: ReactNode;
  footer: ReactNode;
};

/**
 * The login and sign-up pages: the form on the left, and on large screens a panel on PeakSift
 * blue that shows what the product does (a long recording with its moments marked).
 */
export function AuthCard({ title, description, children, footer }: AuthCardProps) {
  return (
    <main className="flex flex-1 bg-chrome lg:p-2">
      <div className="flex w-full flex-col px-6 py-8 sm:px-10 lg:w-[34rem] lg:shrink-0 lg:px-14">
        <Logo />
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-12">
          <h1 className="text-page">{title}</h1>
          <p className="mt-2 text-muted">{description}</p>
          <div className="mt-8">{children}</div>
          <p className="mt-8 text-sm text-muted">{footer}</p>
        </div>
      </div>

      <section
        aria-label="What PeakSift does"
        className="create-band relative hidden flex-1 flex-col justify-between overflow-hidden rounded-canvas border border-border p-12 lg:flex xl:p-16"
      >
        <div className="max-w-lg">
          <p className="font-display text-5xl leading-[1.02] font-extrabold tracking-tight text-balance xl:text-6xl">
            Find the moments worth clipping.
          </p>
          <p className="mt-5 max-w-md text-lg text-pretty text-foreground/80">
            Drop a long video. PeakSift marks the strongest moments and helps you turn them into Shorts for YouTube,
            TikTok and Instagram Reels.
          </p>
        </div>
        <MomentStrip compact className="mt-12" />
      </section>
    </main>
  );
}

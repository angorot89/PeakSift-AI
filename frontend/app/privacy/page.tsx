import { EyeOff, KeyRound, Lock, Server, ShieldCheck, Trash2 } from "lucide-react";
import type { Metadata } from "next";
import { ClosingCta } from "@/components/landing/closing-cta";
import { PageHero, SiteShell } from "@/components/landing/page-blocks";
import { Reveal } from "@/components/landing/reveal";

export const metadata: Metadata = {
  title: "Your data",
  description: "How PeakSift is built to handle your videos, accounts and data.",
};

const FACTS: { title: string; text: string }[] = [
  { title: "Your media is private", text: "Videos, clips, Shorts, images and audio are stored privately and only ever streamed to you after PeakSift checks it is yours. There are no public links." },
  { title: "AI that runs on the server", text: "Face framing and visual search run on PeakSift's own server. Moments and the assistant can use a local model too; the server decides which models are allowed." },
  { title: "Only the permissions posting needs", text: "For YouTube, PeakSift asks for upload access only. Reading analytics is a separate, read-only permission you start yourself." },
  { title: "Tokens are encrypted", text: "Platform tokens are stored encrypted and bound to your account; they are never shown or logged." },
  { title: "Nothing posts without you", text: "PeakSift never publishes, deletes or changes anything on a platform without your click." },
  { title: "Delete what you want", text: "Delete projects and their files, disconnect platforms, and remove collected analytics whenever you choose." },
];

const ICONS = [EyeOff, Server, KeyRound, Lock, ShieldCheck, Trash2];

/** How PeakSift handles data — facts about how it is built, not a legal policy. */
export default function PrivacyPage() {
  return (
    <SiteShell>
      <PageHero
        trail={[{ label: "Your data" }]}
        title="Your data, handled with care"
        lead="How PeakSift is built to handle your videos, your accounts and your numbers."
        cta={null}
      />
      <section className="px-6 py-20">
        <ul className="mx-auto grid max-w-6xl gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FACTS.map((fact, i) => {
            const Icon = ICONS[i];
            return (
              <Reveal as="li" key={fact.title} delay={(i % 3) * 80} className="rounded-card border border-border bg-surface p-6">
                <span className="flex size-11 items-center justify-center rounded-block bg-accent/10 text-accent-soft">
                  <Icon aria-hidden="true" className="size-5" />
                </span>
                <h2 className="mt-4 font-display text-lg font-bold">{fact.title}</h2>
                <p className="mt-1.5 text-muted">{fact.text}</p>
              </Reveal>
            );
          })}
        </ul>
        <p className="mx-auto mt-12 max-w-2xl text-center text-small text-subtle">
          This page explains how PeakSift is built. It is not a legal policy: the privacy policy and terms of service will be
          published before PeakSift opens to the public.
        </p>
      </section>
      <ClosingCta />
    </SiteShell>
  );
}

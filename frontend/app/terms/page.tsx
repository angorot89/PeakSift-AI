import type { Metadata } from "next";
import { LegalPage } from "@/components/landing/legal-page";

export const metadata: Metadata = { title: "Terms of Service", description: "The terms for using PeakSift (draft for legal review)." };

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      updated="27 November 2026"
      intro="These terms explain the agreement between you and [PeakSift legal entity] (“PeakSift”, “we”) when you use the PeakSift website and app. By creating an account you agree to them."
      sections={[
        { heading: "Your account", body: ["You need an account to use PeakSift. Keep your password safe; you are responsible for what happens under your account.", "You must be at least [16] years old, or the age of digital consent where you live, to use PeakSift."] },
        { heading: "Your content", body: ["You keep every right you have in the videos, images, audio and text you upload, and in the clips and Shorts PeakSift makes from them.", "You give PeakSift permission to store and process your content only to provide the service to you: transcribing it, finding moments, rendering clips and Shorts, and posting them where you ask.", "Only upload content you have the right to use, including the rights of the people who appear in it and any music it contains."] },
        { heading: "Acceptable use", body: ["Do not use PeakSift to upload or publish anything illegal, infringing, hateful, or that violates someone's privacy, and do not try to break, overload or reverse-engineer the service.", "We may remove content or suspend accounts that break these rules."] },
        { heading: "AI features", body: ["PeakSift uses AI to suggest moments, edits, hooks and answers. Suggestions can be wrong. You decide what to keep and what to post; review everything before you publish it."] },
        { heading: "Connected platforms", body: ["When you connect YouTube, TikTok or Instagram, PeakSift posts only when you ask it to, with the permissions you granted. Those platforms' own terms and policies apply to what you post there.", "You can disconnect a platform at any time in Settings."] },
        { heading: "Plans and payment", body: ["PeakSift is in early access: every account can use every tool for free. Paid plans are listed on the Pricing page and will start only when billing opens.", "Before any charge, we will show you the price and ask for your agreement. [Billing, renewal, cancellation and refund terms to be completed before billing opens.]"] },
        { heading: "Early access", body: ["PeakSift is still being built. Features may change, be added or be removed, and the service may sometimes be unavailable. Keep your own copies of anything important."] },
        { heading: "Ending your use", body: ["You can stop using PeakSift and delete your projects at any time. We may end or suspend the service, or your access, with notice where reasonable."] },
        { heading: "Liability", body: ["PeakSift is provided “as is”. To the extent the law allows, [PeakSift legal entity] is not liable for indirect or consequential losses, and our total liability is limited to [amount]. Nothing here limits liability that cannot be limited by law."] },
        { heading: "Changes and law", body: ["We may update these terms and will tell you about important changes before they take effect.", "These terms are governed by the laws of [country], and disputes go to the courts of [city], unless the law where you live says otherwise."] },
        { heading: "Contact", body: ["Questions about these terms: [contact email], [postal address]."] },
      ]}
    />
  );
}

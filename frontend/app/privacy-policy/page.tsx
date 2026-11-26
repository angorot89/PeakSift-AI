import type { Metadata } from "next";
import { LegalPage } from "@/components/landing/legal-page";

export const metadata: Metadata = { title: "Privacy Policy", description: "What PeakSift collects and how it is used (draft for legal review)." };

export default function PrivacyPolicyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      updated="27 November 2026"
      intro="This policy explains what personal data [PeakSift legal entity] (“PeakSift”, “we”) collects when you use PeakSift, why, who it is shared with, and the choices you have."
      sections={[
        { heading: "What we collect", body: ["Account: your email address and your password, stored only as a secure hash.", "Your content: the videos, images and audio you upload, their transcripts, and the clips, Shorts and settings you create.", "Connections: when you connect YouTube, TikTok or Instagram, the access tokens those platforms give us, stored encrypted.", "Analytics: if you grant read-only access, the views and watch time YouTube reports for Shorts you published with PeakSift.", "Technical data: server logs with a request id, with sensitive values removed."] },
        { heading: "How we use it", body: ["To run the service for you: to sign you in, transcribe your videos, find moments, render clips and Shorts, post them where you ask and show you how they are doing.", "We do not sell your data, do not show ads, and do not use your content to train AI models."] },
        { heading: "AI processing", body: ["Face framing and visual search run on PeakSift's own servers. Transcription, moment finding and the assistant run on a model chosen by the server: either one on our servers or a hosted provider such as [OpenAI], in which case the audio or transcript needed for that task is sent to that provider. [List the providers used in production.]"] },
        { heading: "Who we share it with", body: ["Hosting and storage providers that run PeakSift for us: [hosting provider], [storage provider].", "The platforms you connect (Google/YouTube, TikTok, Meta/Instagram), only when you ask PeakSift to post or read your analytics.", "Authorities, when the law requires it."] },
        { heading: "Cookies and storage", body: ["PeakSift uses one essential cookie to keep you signed in. Your browser also remembers small preferences, such as whether the sidebar is collapsed. There are no advertising or tracking cookies."] },
        { heading: "How long we keep it", body: ["Your content and account data are kept until you delete them or your account. Deleted files are removed from storage; backups are kept for up to [number] days.", "You can delete collected analytics at any time."] },
        { heading: "Security", body: ["Media is stored privately and only streamed to you after an ownership check; there are no public links. Platform tokens are encrypted, connections use HTTPS, and access is limited to what each feature needs."] },
        { heading: "Your rights", body: ["You can see, correct and delete your data in the app, and disconnect platforms in Settings. To ask for a copy of your data, or to exercise any other right you have under the law where you live, contact [contact email]."] },
        { heading: "Children", body: ["PeakSift is not meant for children under [16] and we do not knowingly collect their data."] },
        { heading: "Changes and contact", body: ["We will tell you about important changes to this policy before they take effect.", "Data controller: [PeakSift legal entity], [postal address]. Questions: [contact email]."] },
      ]}
    />
  );
}

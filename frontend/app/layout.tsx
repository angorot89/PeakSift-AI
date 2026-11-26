import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Geist_Mono, Instrument_Sans, Noto_Sans } from "next/font/google";
import { AuthProvider } from "@/components/auth/auth-provider";
import "./globals.css";

// The interface face (body, controls, labels).
const uiSans = Instrument_Sans({
  variable: "--font-ui",
  subsets: ["latin", "latin-ext"],
});

// The display face: heavy titles (h1, h2, text-display/page/section in globals.css).
const displayFace = Bricolage_Grotesque({
  variable: "--font-display-face",
  subsets: ["latin", "latin-ext"],
});

const uiMono = Geist_Mono({
  variable: "--font-ui-mono",
  subsets: ["latin"],
});

// The face libass renders captions with: the editor preview uses it so lines wrap the same way.
const captionSans = Noto_Sans({
  variable: "--font-caption",
  subsets: ["latin", "latin-ext"],
  weight: ["400", "700"],
  preload: false,
});

// On phones the on-screen keyboard resizes the page, so composers (Ask PeakSift) stay in view.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  interactiveWidget: "resizes-content",
};

export const metadata: Metadata = {
  title: {
    default: "PeakSift AI — Find the moments worth clipping.",
    template: "%s — PeakSift AI",
  },
  description:
    "PeakSift AI helps creators discover the strongest moments inside long-form content and turn them into short-form content for YouTube Shorts, TikTok, and Instagram Reels.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${uiSans.variable} ${displayFace.variable} ${uiMono.variable} ${captionSans.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col font-sans">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}

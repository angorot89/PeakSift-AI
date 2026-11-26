import { ArrowRight, CalendarClock } from "lucide-react";

/** The strip above the website's navigation: what is new, and where to read about it. */
export function Announcement() {
  return (
    <div className="bg-[#0d0f1c] px-4 py-2.5 text-center text-sm text-white">
      <CalendarClock aria-hidden="true" className="mr-2 inline size-4 align-[-3px] text-[#9aabff]" />
      <span className="font-semibold">New: scheduling.</span>{" "}
      <span className="hidden sm:inline">Plan your Shorts for YouTube, TikTok and Instagram Reels a week ahead. </span>
      <a
        href="#publish"
        className="inline-flex min-h-6 items-center gap-1 font-semibold underline underline-offset-4 hover:text-[#9aabff] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
      >
        See how
        <ArrowRight aria-hidden="true" className="size-3.5" />
      </a>
    </div>
  );
}

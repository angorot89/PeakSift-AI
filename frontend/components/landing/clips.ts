// Real Shorts made with PeakSift, shown on the website in place of the drawn examples.
// Each file lives in public/clips/ (an MP4 rendered by PeakSift and its poster frame), made from
// a video its owner agreed to show. While fewer than four exist, the drawn examples are shown.

import type { Platform } from "@/components/landing/scene-parts";

export type RealClip = {
  /** Path under /clips, e.g. "/clips/podcast-pricing.mp4". */
  src: string;
  /** The Short's title, for its label. */
  title?: string;
  /** The channel it was posted on, when it was. */
  channel?: string;
  /** A still from the Short (JPEG/WebP) shown before it plays. */
  poster: string;
  /** What kind of video it came from ("Podcast", "Interview"…). */
  kind: string;
  /** Where it was posted, if it was. */
  platform?: Platform;
};

export const REAL_CLIPS: RealClip[] = [];

/** Real clips replace the drawn ones once there are enough to fill the row. */
export const MIN_REAL_CLIPS = 4;

/**
 * Shorts the PeakSift team makes and posts on its own YouTube channels: code- and
 * Blender-animated quizzes and stories, with no real people. They were not cut by PeakSift from a
 * long video, so the website shows them as the team's own Shorts — never as "made with PeakSift".
 */
export const TEAM_CLIPS: RealClip[] = [
  { src: "/clips/fox-eagle-snake.mp4", poster: "/clips/fox-eagle-snake.jpg", kind: "Quiz", title: "Only one eagle eats a snake", channel: "Think Fast Fox", platform: "youtube" },
  { src: "/clips/pov-not-mommy.mp4", poster: "/clips/pov-not-mommy.jpg", kind: "Animation", title: "Not Mommy", channel: "Lock The Door POV", platform: "youtube" },
  { src: "/clips/fox-only-one-sun.mp4", poster: "/clips/fox-only-one-sun.jpg", kind: "Quiz", title: "Only one has a real sun", channel: "Think Fast Fox", platform: "youtube" },
  { src: "/clips/pov-zombie-treehouse.mp4", poster: "/clips/pov-zombie-treehouse.jpg", kind: "Animation", title: "Zombie-proof treehouse", channel: "Lock The Door POV" },
  { src: "/clips/fox-four-stripe-flag.mp4", poster: "/clips/fox-four-stripe-flag.jpg", kind: "Quiz", title: "Can you beat a pigeon?", channel: "Think Fast Fox", platform: "youtube" },
  { src: "/clips/pov-zombie-container.mp4", poster: "/clips/pov-zombie-container.jpg", kind: "Animation", title: "Zombie-proof shipping container", channel: "Lock The Door POV" },
];

/** A Short that stays on YouTube and is embedded, never copied into this repository. */
export type YouTubeShort = { id: string; title: string };

/**
 * Stream highlights from the Amgoro clips channel, shown by embedding the live YouTube Shorts
 * (the creator's decision). The streams belong to the streamers in them; nothing is hosted here.
 */
export const AMGORO = {
  channel: "Amgoro Shorts",
  url: "",
  shorts: [] as YouTubeShort[],
};

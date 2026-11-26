// Real Shorts made with PeakSift, shown on the website in place of the drawn examples.
// Each file lives in public/clips/ (an MP4 rendered by PeakSift and its poster frame), made from
// a video its owner agreed to show. While fewer than four exist, the drawn examples are shown.

import type { Platform } from "@/components/landing/scene-parts";

export type RealClip = {
  /** Path under /clips, e.g. "/clips/podcast-pricing.mp4". */
  src: string;
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

// PeakSift's plans as shown on the website. Billing is not live: during early access every
// account has everything for free, and these plans and limits apply only once billing opens.

export type Plan = {
  key: "free" | "starter" | "creator" | "pro";
  name: string;
  tagline: string;
  monthly: number;
  /** Price per month when paid yearly (two months free). */
  yearly: number;
  hours: number;
  popular?: boolean;
  highlights: string[];
};

export const PLANS: Plan[] = [
  {
    key: "free",
    name: "Free",
    tagline: "Find your first moments and make Shorts.",
    monthly: 0,
    yearly: 0,
    hours: 2,
    highlights: ["AI moments and Find Clips", "Editor with smart reframe and captions", "Full-HD downloads, no watermark", "Morocco Mode"],
  },
  {
    key: "starter",
    name: "Starter",
    tagline: "Post regularly from one place.",
    monthly: 12,
    yearly: 10,
    hours: 10,
    highlights: ["Everything in Free", "Publish to YouTube, TikTok and Instagram", "Scheduling and posting times", "Auto Edit", "One brand in Brand Studio"],
  },
  {
    key: "creator",
    name: "Creator",
    tagline: "Every tool, for a steady stream of Shorts.",
    monthly: 24,
    yearly: 20,
    hours: 30,
    popular: true,
    highlights: ["Everything in Starter", "B-roll, visual search and sound", "Unlimited templates", "Analytics and insights", "Ask PeakSift"],
  },
  {
    key: "pro",
    name: "Pro",
    tagline: "The most hours, the fastest renders.",
    monthly: 39,
    yearly: 32.5,
    hours: 80,
    highlights: ["Everything in Creator", "Priority rendering", "Up to five brands", "Longest uploads"],
  },
];

/** The comparison table: one row per capability, one value per plan (true, false or text). */
export const COMPARISON: { group: string; rows: { label: string; values: (boolean | string)[] }[] }[] = [
  {
    group: "Video",
    rows: [
      { label: "Hours of video each month", values: ["2", "10", "30", "80"] },
      { label: "Longest upload", values: ["1 hour", "3 hours", "6 hours", "12 hours"] },
      { label: "Full-HD vertical renders (1080×1920)", values: [true, true, true, true] },
      { label: "No watermark", values: [true, true, true, true] },
      { label: "Priority rendering", values: [false, false, false, true] },
    ],
  },
  {
    group: "Finding moments",
    rows: [
      { label: "AI moments with reasons", values: [true, true, true, true] },
      { label: "Find Clips", values: [true, true, true, true] },
      { label: "Morocco Mode", values: [true, true, true, true] },
    ],
  },
  {
    group: "Editing",
    rows: [
      { label: "Smart reframe and layouts", values: [true, true, true, true] },
      { label: "Word-by-word captions and hooks", values: [true, true, true, true] },
      { label: "Auto Edit", values: [false, true, true, true] },
      { label: "B-roll and visual search", values: [false, false, true, true] },
      { label: "Music, effects and ducking", values: [false, false, true, true] },
      { label: "Brands", values: ["—", "1", "1", "5"] },
      { label: "Templates", values: ["—", "3", "Unlimited", "Unlimited"] },
    ],
  },
  {
    group: "Publishing and results",
    rows: [
      { label: "Publish to YouTube, TikTok and Instagram", values: [false, true, true, true] },
      { label: "Scheduling and posting times", values: [false, true, true, true] },
      { label: "Analytics and insights", values: [false, false, true, true] },
      { label: "Ask PeakSift", values: [false, false, true, true] },
    ],
  },
];

export const price = (value: number) => (Number.isInteger(value) ? `$${value}` : `$${value.toFixed(2)}`);

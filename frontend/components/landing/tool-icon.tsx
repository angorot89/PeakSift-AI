import {
  AudioLines,
  BarChart3,
  CalendarClock,
  Captions,
  Crop,
  Image as ImageIcon,
  Languages,
  MessageCircle,
  Palette,
  Search,
  Sparkles,
  Wand2,
  type LucideIcon,
} from "lucide-react";

/** Each tool's icon and tint, shared by the menus, the toolkit and the tool pages. */
export const TOOL_ICONS: Record<string, { icon: LucideIcon; tint: string }> = {
  "ai-moments": { icon: Sparkles, tint: "bg-[#3d5afe]/10 text-[#2f4ae0]" },
  "find-clips": { icon: Search, tint: "bg-[#3d5afe]/10 text-[#2f4ae0]" },
  "auto-edit": { icon: Wand2, tint: "bg-violet-500/10 text-violet-700" },
  "smart-reframe": { icon: Crop, tint: "bg-violet-500/10 text-violet-700" },
  captions: { icon: Captions, tint: "bg-amber-500/15 text-amber-800" },
  visuals: { icon: ImageIcon, tint: "bg-amber-500/15 text-amber-800" },
  music: { icon: AudioLines, tint: "bg-rose-500/10 text-rose-700" },
  "brand-studio": { icon: Palette, tint: "bg-rose-500/10 text-rose-700" },
  publish: { icon: CalendarClock, tint: "bg-emerald-500/10 text-emerald-700" },
  analytics: { icon: BarChart3, tint: "bg-emerald-500/10 text-emerald-700" },
  ask: { icon: MessageCircle, tint: "bg-sky-500/10 text-sky-700" },
  "morocco-mode": { icon: Languages, tint: "bg-sky-500/10 text-sky-700" },
};

export function ToolIcon({ slug, size = "md" }: { slug: string; size?: "md" | "lg" }) {
  const entry = TOOL_ICONS[slug] ?? TOOL_ICONS["ai-moments"];
  return (
    <span className={`flex items-center justify-center rounded-block ${entry.tint} ${size === "lg" ? "size-14" : "size-11"}`}>
      <entry.icon aria-hidden="true" className={size === "lg" ? "size-7" : "size-5"} />
    </span>
  );
}

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

// One shape for every button in the product: a softly rounded rectangle, never a pill.
const base =
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-[color,background-color,border-color,box-shadow] duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [&_svg]:size-4 [&_svg]:shrink-0";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-foreground text-background shadow-sm hover:bg-zinc-200",
  secondary:
    "border border-border-strong bg-surface-2 text-foreground hover:border-white/25 hover:bg-surface-3",
  ghost: "text-muted hover:bg-white/[0.06] hover:text-foreground",
  danger: "border border-danger/40 bg-danger/10 text-rose-100 hover:bg-danger/20",
};

const sizes: Record<ButtonSize, string> = {
  // Touch screens get taller targets (40 / 44 px) without changing desktop density.
  sm: "h-8 px-3 text-small pointer-coarse:h-10",
  md: "h-10 px-4 text-sm pointer-coarse:h-11",
  lg: "h-12 px-6 text-lead",
};

export function buttonClasses(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
  className = "",
): string {
  return `${base} ${variants[variant]} ${sizes[size]} ${className}`;
}

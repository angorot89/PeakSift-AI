export type ButtonVariant = "primary" | "secondary";
export type ButtonSize = "md" | "lg";

const base =
  "inline-flex items-center justify-center gap-2 rounded-full font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-foreground text-background hover:bg-zinc-200",
  secondary:
    "border border-border bg-white/[0.03] text-foreground hover:border-white/20 hover:bg-white/[0.06]",
};

const sizes: Record<ButtonSize, string> = {
  md: "h-9 px-4 text-sm",
  lg: "h-12 px-6 text-[15px]",
};

export function buttonClasses(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
  className = "",
): string {
  return `${base} ${variants[variant]} ${sizes[size]} ${className}`;
}

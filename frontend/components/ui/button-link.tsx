import Link from "next/link";
import type { ComponentProps } from "react";

type Variant = "primary" | "secondary";
type Size = "md" | "lg";

const base =
  "inline-flex items-center justify-center gap-2 rounded-full font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

const variants: Record<Variant, string> = {
  primary: "bg-foreground text-background hover:bg-zinc-200",
  secondary:
    "border border-border bg-white/[0.03] text-foreground hover:border-white/20 hover:bg-white/[0.06]",
};

const sizes: Record<Size, string> = {
  md: "h-9 px-4 text-sm",
  lg: "h-12 px-6 text-[15px]",
};

type ButtonLinkProps = ComponentProps<"a"> & {
  href: string;
  variant?: Variant;
  size?: Size;
};

export function ButtonLink({
  href,
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ButtonLinkProps) {
  const classes = `${base} ${variants[variant]} ${sizes[size]} ${className}`;

  // In-page anchors use a plain <a>: next/link ignores a click on the current
  // hash, so a repeated click (e.g. after scrolling back up) would not scroll.
  if (href.startsWith("#")) {
    return <a href={href} className={classes} {...props} />;
  }

  return <Link href={href} className={classes} {...props} />;
}

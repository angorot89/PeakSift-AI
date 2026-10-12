import Link from "next/link";
import type { ComponentProps } from "react";
import { buttonClasses, type ButtonSize, type ButtonVariant } from "@/components/ui/button-styles";

type ButtonLinkProps = ComponentProps<"a"> & {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
};

export function ButtonLink({
  href,
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ButtonLinkProps) {
  const classes = buttonClasses(variant, size, className);

  // In-page anchors use a plain <a>: next/link ignores a click on the current
  // hash, so a repeated click (e.g. after scrolling back up) would not scroll.
  if (href.startsWith("#")) {
    return <a href={href} className={classes} {...props} />;
  }

  return <Link href={href} className={classes} {...props} />;
}

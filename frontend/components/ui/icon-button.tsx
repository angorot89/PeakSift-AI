import type { ComponentProps } from "react";
import { buttonClasses, type ButtonVariant } from "@/components/ui/button-styles";

type IconButtonProps = ComponentProps<"button"> & {
  /** Required: an icon alone has no visible name. */
  "aria-label": string;
  variant?: Exclude<ButtonVariant, "primary">;
  size?: "sm" | "md";
};

/** A square button holding only an icon (36 px; 40 px on touch screens). */
export function IconButton({ variant = "ghost", size = "md", className = "", type = "button", ...props }: IconButtonProps) {
  const square = size === "sm" ? "size-8 px-0 pointer-coarse:size-10" : "size-9 px-0 pointer-coarse:size-11";
  return (
    <button
      type={type}
      className={buttonClasses(variant, "sm", `${square} disabled:cursor-not-allowed disabled:opacity-60 ${className}`)}
      {...props}
    />
  );
}

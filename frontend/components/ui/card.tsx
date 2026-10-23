import type { ComponentProps, ElementType, ReactNode } from "react";

type CardProps = {
  as?: ElementType;
  /** "none" for media that runs to the edge. */
  padding?: "none" | "sm" | "md";
  /** A card that is itself a link or a button: lifts on hover. */
  interactive?: boolean;
  className?: string;
  children: ReactNode;
} & Omit<ComponentProps<"div">, "className" | "children">;

const PADDING = { none: "", sm: "p-3 sm:p-4", md: "p-4 sm:p-5" };

/** The one content surface: a soft panel on the page, never a box inside a box inside a box. */
export function Card({ as: Tag = "div", padding = "md", interactive = false, className = "", children, ...props }: CardProps) {
  return (
    <Tag
      className={`rounded-2xl border border-border bg-surface ${PADDING[padding]} ${
        interactive
          ? "transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          : ""
      } ${className}`}
      {...props}
    >
      {children}
    </Tag>
  );
}

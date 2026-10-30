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

/** The card look for elements that are not a plain container (e.g. a Next <Link> card). */
export function cardClasses({ padding = "md", interactive = false }: { padding?: keyof typeof PADDING; interactive?: boolean } = {}) {
  return `rounded-card border border-border bg-surface shadow-card ${PADDING[padding]} ${
    interactive
      ? "transition-[border-color,background-color,transform] duration-200 ease-out-soft hover:-translate-y-px hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:hover:translate-y-0"
      : ""
  }`;
}

/** The one content surface: a soft panel on the page, never a box inside a box inside a box. */
export function Card({ as: Tag = "div", padding = "md", interactive = false, className = "", children, ...props }: CardProps) {
  return (
    <Tag
      className={`${cardClasses({ padding, interactive })} ${className}`}
      {...props}
    >
      {children}
    </Tag>
  );
}

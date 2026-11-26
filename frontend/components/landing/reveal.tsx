"use client";

import { type ElementType, type ReactNode, useEffect, useRef, useState } from "react";

/** True once the element has scrolled into view (and stays true). */
export function useInView<T extends Element>(rootMargin = "0px 0px -15% 0px") {
  const ref = useRef<T>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [rootMargin]);
  return { ref, inView };
}

/**
 * Slides its content in once when it scrolls into view. `scene` also holds every animation inside
 * paused until then, so an illustration plays when it is seen, not when the page loads.
 */
export function Reveal({
  as: Tag = "div",
  scene = false,
  delay = 0,
  className = "",
  children,
}: {
  as?: ElementType;
  scene?: boolean;
  delay?: number;
  className?: string;
  children: ReactNode;
}) {
  const { ref, inView } = useInView<HTMLElement>();
  return (
    <Tag
      ref={ref}
      style={delay ? { animationDelay: `${delay}ms` } : undefined}
      className={`lp-reveal ${scene ? "lp-scene" : ""} ${inView ? "is-in" : ""} ${className}`}
    >
      {children}
    </Tag>
  );
}

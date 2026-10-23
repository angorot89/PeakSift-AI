"use client";

import { useState } from "react";
import { niceMax, reportingDay } from "@/lib/performance";

// One series per chart (never two y-scales): a validated single hue on the dark surface.
const BAR = "#ea580c";
const HEIGHT = 140;
const BAR_MAX = 24;
const GAP = 2;

type Point = { date: string; value: number | null };

/**
 * Daily columns for one metric. Missing days are gaps with a "not reported" tooltip — never a
 * zero-height bar. Every bar is focusable and shows its day and value on hover or focus; the
 * same values are in the table below the charts.
 */
export function DailyChart({
  title,
  points,
  format,
}: {
  title: string;
  points: Point[];
  format: (value: number | null) => string;
}) {
  const [active, setActive] = useState<number | null>(null);
  const top = niceMax(points.map((p) => p.value));
  const ticks = [top, top / 2, 0];
  const shown = active !== null ? points[active] : null;

  return (
    <figure className="min-w-0">
      <figcaption className="mb-2 flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium text-foreground">{title}</span>
        <span aria-live="polite" className="tabular text-xs text-muted">
          {shown ? (
            <>
              <span className="font-semibold text-foreground">{format(shown.value)}</span> · {reportingDay(shown.date)}
            </>
          ) : (
            `${points.length} reporting days`
          )}
        </span>
      </figcaption>
      <div className="flex gap-2">
        <div aria-hidden="true" className="tabular flex w-10 shrink-0 flex-col justify-between text-right text-caption text-subtle" style={{ height: HEIGHT }}>
          {ticks.map((tick) => (
            <span key={tick} className="-my-1.5">{format(tick)}</span>
          ))}
        </div>
        <div className="relative min-w-0 flex-1">
          <div aria-hidden="true" className="absolute inset-x-0 top-0 border-t border-border" />
          <div aria-hidden="true" className="absolute inset-x-0 border-t border-border" style={{ top: HEIGHT / 2 }} />
          <div
            role="list"
            aria-label={title}
            className="relative flex items-end border-b border-border-strong"
            style={{ height: HEIGHT, gap: GAP }}
            onPointerLeave={() => setActive(null)}
          >
            {points.map((point, index) => {
              const height = point.value === null ? 0 : Math.max(2, (point.value / top) * HEIGHT);
              const label = `${reportingDay(point.date)}: ${point.value === null ? "not reported" : format(point.value)}`;
              return (
                <button
                  key={point.date}
                  type="button"
                  role="listitem"
                  aria-label={label}
                  title={label}
                  onPointerEnter={() => setActive(index)}
                  onFocus={() => setActive(index)}
                  onBlur={() => setActive(null)}
                  className="group flex h-full min-w-0 flex-1 items-end justify-center rounded-sm focus-visible:outline-2 focus-visible:outline-accent"
                >
                  {point.value === null ? (
                    <span className="mb-0.5 h-px w-full max-w-6 bg-border-strong" />
                  ) : (
                    <span
                      className="w-full rounded-t transition-opacity group-hover:opacity-80"
                      style={{ height, maxWidth: BAR_MAX, background: BAR, opacity: active === null || active === index ? 1 : 0.55 }}
                    />
                  )}
                </button>
              );
            })}
          </div>
          {points.length ? (
            <div aria-hidden="true" className="tabular mt-1.5 flex justify-between text-caption text-subtle">
              <span>{reportingDay(points[0].date)}</span>
              {points.length > 1 ? <span>{reportingDay(points[points.length - 1].date)}</span> : null}
            </div>
          ) : null}
        </div>
      </div>
    </figure>
  );
}

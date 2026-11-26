"use client";

import { Check, Minus, Sparkles } from "lucide-react";
import { useState } from "react";
import { COMPARISON, PLANS, price } from "@/components/landing/plans";
import { ButtonLink } from "@/components/ui/button-link";

type Billing = "monthly" | "yearly";

/** Monthly or yearly: a two-way switch (pressed buttons). */
function BillingSwitch({ billing, onChange }: { billing: Billing; onChange: (billing: Billing) => void }) {
  return (
    <div role="group" aria-label="Billing period" className="inline-flex rounded-full border border-white/30 bg-white/15 p-1 backdrop-blur">
      {(["monthly", "yearly"] as const).map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={billing === option}
          onClick={() => onChange(option)}
          className={`inline-flex min-h-10 items-center gap-2 rounded-full px-5 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white ${
            billing === option ? "bg-white text-[#1b2a8f] shadow" : "text-white hover:bg-white/10"
          }`}
        >
          {option === "monthly" ? "Monthly" : "Yearly"}
          {option === "yearly" ? (
            <span className={`rounded-full px-2 py-0.5 text-caption ${billing === option ? "bg-[#e3f25c] text-[#15170a]" : "bg-white/20 text-white"}`}>
              2 months free
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

/**
 * The plans: four cards with a monthly/yearly switch, then a full comparison. Billing is not
 * live, so every button starts a free account and the page says so.
 */
export function PricingPlans() {
  const [billing, setBilling] = useState<Billing>("monthly");
  return (
    <>
      <div className="mt-8 flex justify-center">
        <BillingSwitch billing={billing} onChange={setBilling} />
      </div>
      <ul className="mx-auto mt-12 grid max-w-6xl gap-4 text-left md:grid-cols-2 xl:grid-cols-4">
        {PLANS.map((plan, i) => {
          const amount = billing === "monthly" ? plan.monthly : plan.yearly;
          return (
            <li
              key={plan.key}
              style={{ animationDelay: `${i * 80}ms` }}
              className={`lp-pop relative flex flex-col rounded-canvas border bg-surface p-6 ${
                plan.popular ? "border-2 border-accent shadow-[0_30px_60px_-30px_rgb(61_90_254/0.6)] xl:-translate-y-3" : "border-border shadow-[0_20px_40px_-30px_rgb(14_18_34/0.4)]"
              }`}
            >
              {plan.popular ? (
                <span className="absolute -top-3.5 left-1/2 inline-flex -translate-x-1/2 items-center gap-1 rounded-full bg-accent-fill px-3 py-1 text-caption font-semibold whitespace-nowrap text-white">
                  <Sparkles aria-hidden="true" className="size-3.5" />
                  Most popular
                </span>
              ) : null}
              <p className="font-display text-2xl font-extrabold">{plan.name}</p>
              <p className="mt-1 min-h-12 text-small text-muted">{plan.tagline}</p>
              <p className="mt-4 flex items-baseline gap-1.5">
                <span className="font-display text-5xl font-extrabold tracking-tight">{price(amount)}</span>
                <span className="text-muted">/ month</span>
              </p>
              <p className="mt-1 min-h-5 text-small text-subtle">
                {plan.monthly === 0 ? "Free forever" : billing === "yearly" ? `${price(plan.yearly * 12)} billed yearly` : "Billed monthly"}
              </p>
              <ButtonLink href="/register" variant={plan.popular ? "primary" : "secondary"} className={`mt-6 w-full ${plan.popular ? "lp-key" : ""}`}>
                {plan.monthly === 0 ? "Start free" : `Start with ${plan.name}`}
              </ButtonLink>
              <p className="mt-6 text-small font-semibold text-foreground">{plan.hours} hours of video a month</p>
              <ul className="mt-3 space-y-2.5">
                {plan.highlights.map((item) => (
                  <li key={item} className="flex items-start gap-2 text-sm text-muted">
                    <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-success" />
                    {item}
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
      <p className="mx-auto mt-8 max-w-2xl text-center text-small text-muted">
        PeakSift is in early access: every account has every tool for free until billing opens. Plans and limits apply from
        then, and nothing is ever charged without your agreement.
      </p>
    </>
  );
}

/** Every capability, plan by plan. */
export function ComparisonTable() {
  return (
    <div className="mx-auto mt-12 max-w-6xl overflow-x-auto rounded-canvas border border-border bg-surface">
      <table className="w-full min-w-[44rem] border-collapse text-left text-sm">
        <caption className="sr-only">What each plan includes</caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="p-4 font-display text-base font-bold">
              Compare plans
            </th>
            {PLANS.map((plan) => (
              <th key={plan.key} scope="col" className={`p-4 text-center font-display text-base font-bold ${plan.popular ? "text-accent-soft" : ""}`}>
                {plan.name}
              </th>
            ))}
          </tr>
        </thead>
        {COMPARISON.map((group) => (
          <tbody key={group.group}>
            <tr className="bg-background">
              <th scope="colgroup" colSpan={PLANS.length + 1} className="px-4 py-2.5 text-small font-semibold text-subtle">
                {group.group}
              </th>
            </tr>
            {group.rows.map((row) => (
              <tr key={row.label} className="border-t border-border">
                <th scope="row" className="p-4 font-normal text-foreground">
                  {row.label}
                </th>
                {row.values.map((value, i) => (
                  <td key={PLANS[i].key} className="p-4 text-center">
                    {value === true ? (
                      <>
                        <Check aria-hidden="true" className="mx-auto size-5 text-success" />
                        <span className="sr-only">Included</span>
                      </>
                    ) : value === false ? (
                      <>
                        <Minus aria-hidden="true" className="mx-auto size-5 text-subtle/60" />
                        <span className="sr-only">Not included</span>
                      </>
                    ) : (
                      <span className="font-medium text-foreground">{value}</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

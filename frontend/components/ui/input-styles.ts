// One look for every text input, textarea and select (44 px tall on touch screens).
export const inputBase =
  "w-full rounded-lg border border-border-strong bg-white/[0.03] text-foreground outline-none transition-colors placeholder:text-subtle focus:border-accent/60 focus-visible:ring-2 focus-visible:ring-accent/40 aria-[invalid=true]:border-rose-500/60 disabled:cursor-not-allowed disabled:opacity-60";

export const inputClasses = `${inputBase} h-10 px-3.5 text-sm pointer-coarse:h-11`;
export const textareaClasses = `${inputBase} px-3.5 py-2.5 text-sm leading-relaxed`;

type SectionHeadingProps = {
  title: string;
  description?: string;
};

/** A landing-page section's title and one line of context, left-aligned with the content. */
export function SectionHeading({ title, description }: SectionHeadingProps) {
  return (
    <div className="max-w-2xl">
      <h2 className="text-3xl font-semibold tracking-tight text-balance sm:text-5xl">{title}</h2>
      {description ? (
        <p className="mt-4 text-base leading-relaxed text-pretty text-muted sm:text-lg">{description}</p>
      ) : null}
    </div>
  );
}

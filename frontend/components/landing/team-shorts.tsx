import { ClipVideo } from "@/components/landing/clip-video";
import { AMGORO, TEAM_CLIPS } from "@/components/landing/clips";
import { Reveal } from "@/components/landing/reveal";
import { YouTubeShort } from "@/components/landing/youtube-short";

/**
 * Real Shorts from the team's own channels. They are labelled as the team's work, not as Shorts
 * PeakSift cut from a long video.
 */
export function TeamShorts() {
  if (TEAM_CLIPS.length === 0) return null;
  return (
    <section id="our-shorts" className="scroll-mt-24 border-y border-border bg-[#0d0f1c] px-6 py-24 text-white">
      <div className="mx-auto max-w-6xl">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-4xl font-extrabold tracking-tight text-balance text-white sm:text-5xl">Shorts from our own channels</h2>
          <p className="mt-4 text-lg text-pretty text-white/80">
            We make Shorts too — quizzes and animated stories we create and post on YouTube. Press play.
          </p>
        </Reveal>
        <ul className="mt-14 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {TEAM_CLIPS.map((clip, i) => (
            <Reveal as="li" key={clip.src} delay={(i % 6) * 70} className="min-w-0">
              <ClipVideo clip={clip} className="transition-transform duration-300 hover:-translate-y-1" />
              <p className="mt-3 line-clamp-2 text-sm font-semibold text-white">{clip.title}</p>
              <p className="mt-0.5 text-small text-white/60">
                {clip.channel} · {clip.kind}
              </p>
            </Reveal>
          ))}
        </ul>
        <p className="mt-10 text-center text-small text-white/60">Made by the PeakSift team for our own channels.</p>
        {AMGORO.shorts.length > 0 ? (
          <div className="mt-20">
            <Reveal className="mx-auto max-w-2xl text-center">
              <h3 className="font-display text-3xl font-extrabold tracking-tight text-white sm:text-4xl">Stream highlights from {AMGORO.channel}</h3>
              <p className="mt-3 text-white/80">Moments we clip from live streams and post on our clips channel.</p>
            </Reveal>
            <ul className="mt-10 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
              {AMGORO.shorts.map((short) => (
                <li key={short.id} className="min-w-0">
                  <YouTubeShort short={short} />
                  <p className="mt-3 line-clamp-2 text-sm font-semibold text-white">{short.title}</p>
                </li>
              ))}
            </ul>
            <p className="mt-8 text-center text-small text-white/60">
              Played from YouTube. The streams belong to the streamers who appear in them.
              {AMGORO.url ? (
                <>
                  {" "}
                  <a href={AMGORO.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-white underline underline-offset-4">
                    Visit the channel
                  </a>
                </>
              ) : null}
            </p>
          </div>
        ) : null}
      </div>
    </section>
  );
}

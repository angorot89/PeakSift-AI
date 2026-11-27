import { Anton, Bangers, Bebas_Neue, Lalezar, Luckiest_Guy, Titan_One } from "next/font/google";

// The display fonts of the creator caption styles, self-hosted by Next (Google Fonts, OFL /
// Apache). The server renders with the same families (pinned files, see the backend's
// caption_fonts.py); the preview is close, not pixel-exact. Loaded only where captions show.
const anton = Anton({ weight: "400", subsets: ["latin", "latin-ext"], preload: false });
const bangers = Bangers({ weight: "400", subsets: ["latin", "latin-ext"], preload: false });
const bebas = Bebas_Neue({ weight: "400", subsets: ["latin", "latin-ext"], preload: false });
const titan = Titan_One({ weight: "400", subsets: ["latin", "latin-ext"], preload: false });
const luckiest = Luckiest_Guy({ weight: "400", subsets: ["latin"], preload: false });
const lalezar = Lalezar({ weight: "400", subsets: ["arabic", "latin", "latin-ext"], preload: false });

const BY_FAMILY: Record<string, string> = {
  Anton: anton.style.fontFamily,
  Bangers: bangers.style.fontFamily,
  "Bebas Neue": bebas.style.fontFamily,
  "Titan One": titan.style.fontFamily,
  "Luckiest Guy": luckiest.style.fontFamily,
  Lalezar: lalezar.style.fontFamily,
};

/** The CSS font stack of a caption style: its display font, then the server's caption font
 * (Noto Sans) for characters the display font lacks — as libass falls back. */
export function captionFontFamily(family: string | null | undefined): string {
  const base = "var(--font-caption), 'Noto Sans', sans-serif";
  const display = family ? BY_FAMILY[family] : undefined;
  return display ? `${display}, ${base}` : base;
}

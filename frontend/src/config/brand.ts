/**
 * VOXORA brand configuration: the single source of the product's name, voice
 * and taglines. Import from here instead of hardcoding brand copy.
 *
 * VOX (voice) + ORA (aura): where stories find their voice.
 */
export const brand = {
  name: "VOXORA",
  descriptor: "AI Audiobook Studio",
  tagline: "Where stories find their voice.",
  description: "VOXORA transforms books and documents into immersive audiobooks with natural AI narration.",
  taglines: {
    bringToLife: "Bring your books to life.",
    beyondThePage: "Listen beyond the page.",
    yourWorld: "Your stories. Your voice. Your world.",
    pagesToExperiences: "Turn pages into experiences.",
  },
  colors: {
    obsidian: "#140B26",
    carbon: "#1B1131",
    plum: "#271A45",
    orchid: "#C45CFF",
    mint: "#7EEFC9",
    amber: "#FFB86B",
    coral: "#FF6B81",
    ice: "#F3EFFA",
    mist: "#AA9FC2",
  },
} as const;

/** "VOXORA · Library"; the bare brand + tagline for the home page. */
export function pageTitle(section?: string | null): string {
  return section ? `${brand.name} · ${section}` : `${brand.name} — ${brand.tagline}`;
}

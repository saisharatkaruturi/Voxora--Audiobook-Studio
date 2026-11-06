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
    obsidian: "#0B3048",
    carbon: "#0E3753",
    plum: "#144566",
    orchid: "#B9F12F",
    mint: "#B9F12F",
    amber: "#FFB86B",
    coral: "#FF6B81",
    ice: "#F2F0E9",
    mist: "#A9B6BE",
  },
} as const;

/** "VOXORA · Library"; the bare brand + tagline for the home page. */
export function pageTitle(section?: string | null): string {
  return section ? `${brand.name} · ${section}` : `${brand.name} — ${brand.tagline}`;
}

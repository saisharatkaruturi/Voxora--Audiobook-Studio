let names: Intl.DisplayNames | null = null;
try {
  names = new Intl.DisplayNames(["en"], { type: "language" });
} catch {
  names = null;
}

/** Human language name for an ISO code, preferring the server's label when it is a real name. */
export function languageName(code: string | null | undefined, serverName?: string | null): string {
  if (!code) return "Unknown";
  if (code === "mul") return "Multilingual";
  if (serverName && serverName.toLowerCase() !== code.toLowerCase()) return serverName;
  try {
    return names?.of(code) ?? code;
  } catch {
    return code;
  }
}

/** Languages we surface first, per the product's audience. */
export const FEATURED_LANGUAGES = ["en", "hi", "te", "ta", "kn", "ml", "bn", "mr", "gu", "ur"];

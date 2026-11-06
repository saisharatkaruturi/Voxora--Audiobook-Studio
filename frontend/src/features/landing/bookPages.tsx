import type { Spread } from "@/components/book3d/OpenBook";

/**
 * The pages of the landing page's book: "The Starlight Archive", an original
 * short story written for VOXORA (free to use, CC0).
 */

export const BOOK_TITLE = "The Starlight Archive";
export const BOOK_AUTHOR = "A VOXORA Original";

export type SpreadKey = "reading" | "contents" | "device";

/** What narration cleanup does to this passage: say the time the way a person would. */
export function spoken(text: string, cleanup: boolean) {
  return cleanup ? text.replace("11:11 p.m.", "eleven eleven p.m.") : text;
}

const CONTENTS: [string, string][] = [
  ["Part One: The Archive", ""],
  ["Chapter 1: The Night Shift", "6:12"],
  ["Chapter 2: The Voice in the Stacks", "7:40"],
  ["Chapter 3: The Missing Chapter", "8:05"],
  ["Part Two: The Sky", ""],
  ["Chapter 4: Starfall", "9:31"],
  ["Epilogue: Every Story Has a Voice", "4:22"],
];

function Folio({ n, side }: { n: number; side: "l" | "r" }) {
  return <div className={`bp-folio bp-folio-${side}`}>{n}</div>;
}

function ChapterOpener() {
  return (
    <>
      <div className="bp-part">Part One · The Archive</div>
      <div className="bp-chapter-no">Chapter 1</div>
      <div className="bp-chapter-title">The Night Shift</div>
      <div className="bp-ornament" aria-hidden>
        * * *
      </div>
      <p className="bp-epigraph">For everyone who was ever read to sleep.</p>
      <Folio n={2} side="l" />
    </>
  );
}

function Passage({
  sentences,
  active,
  cleanup,
  onSeek,
}: {
  sentences: { text: string }[];
  active: number;
  cleanup: boolean;
  onSeek: (i: number) => void;
}) {
  // The voices split the passage into the same five sentences: two, then three.
  const paras = [sentences.slice(0, 2), sentences.slice(2)];
  let n = 0;
  return (
    <>
      <div className="bp-runhead">{BOOK_TITLE}</div>
      {paras.map((p, pi) => (
        <p key={pi} className={pi === 0 ? "bp-p bp-first" : "bp-p"}>
          {p.map((s) => {
            const i = n++;
            return (
              <span key={i} className="bp-sent" data-on={i === active ? "" : undefined} onClick={() => onSeek(i)} title="Play from here">
                {spoken(s.text, cleanup)}{" "}
              </span>
            );
          })}
        </p>
      ))}
      <Folio n={3} side="r" />
    </>
  );
}

function Contents() {
  return (
    <>
      <div className="bp-runhead">Contents</div>
      <ul className="bp-toc">
        {CONTENTS.map(([t, d]) => (
          <li key={t} className={d ? "" : "bp-toc-part"}>
            <span>{t}</span>
            {d && <span className="bp-toc-time">{d}</span>}
          </li>
        ))}
      </ul>
      <Folio n={4} side="l" />
    </>
  );
}

function FoundNotes() {
  return (
    <>
      <div className="bp-runhead">Found by VOXORA</div>
      <p className="bp-p bp-note">Nine sections, read from the file in under a second.</p>
      <p className="bp-p bp-note">Seven are narrated: two parts, four chapters and the epilogue, about thirty-six minutes in all.</p>
      <p className="bp-p bp-note">The title page and the contents stay in the book but are not read aloud.</p>
      <Folio n={5} side="r" />
    </>
  );
}

function Colophon() {
  return (
    <>
      <div className="bp-runhead">This copy</div>
      <div className="bp-colophon">
        <p className="bp-p">Saved on this device.</p>
        <p className="bp-p">Seven chapters, 36 minutes, 17 MB.</p>
        <p className="bp-p">Plays without a connection, and picks up at the sentence where you stopped.</p>
        <p className="bp-p">The VOXORA server deleted its copy the moment this one arrived.</p>
      </div>
      <Folio n={6} side="l" />
    </>
  );
}

export function buildSpread(
  key: SpreadKey,
  passage: { sentences: { text: string }[]; active: number; cleanup: boolean; onSeek: (i: number) => void },
): Spread {
  const right = <Passage {...passage} />;
  if (key === "contents") return { key, left: <Contents />, right: <FoundNotes /> };
  if (key === "device") return { key, left: <Colophon />, right };
  return { key, left: <ChapterOpener />, right };
}

// --------------------------------------------------------------------------- riffle
// While nobody is listening, the book leafs through the rest of the story.

const STORY: { head: string; title?: string; paras: string[] }[] = [
  {
    head: "Chapter 2",
    title: "The Voice in the Stacks",
    paras: [
      "The sentence on the page read: Asha will climb the ladder before the clock strikes the quarter.",
      "Below her, the great clock of the observatory struck the quarter. The voice paused, as if it were waiting for her to catch up.",
    ],
  },
  {
    head: "The Voice in the Stacks",
    paras: [
      "“Who is reading?” Asha whispered.",
      "“Whoever is listening,” said the book. “That is how stories work. They wait on a shelf until somebody needs them.”",
      "Outside, the first star of the Perseids slid across the window like a struck match.",
    ],
  },
  {
    head: "Chapter 3",
    title: "The Missing Chapter",
    paras: [
      "The book had forty chapters. Chapter thirty-nine ended with a lighthouse keeper's daughter running toward the sea, and chapter forty began years later, with a woman who would not speak about that night.",
      "Between them, someone had torn out a single page.",
    ],
  },
  {
    head: "The Missing Chapter",
    paras: [
      "Asha found the torn edge with her fingertip. Pressed into the spine was a ticket for the night train to Kalka, dated the year her grandmother left the hills and never came back.",
      "“You kept her place,” Asha said. The book did not answer, but the page beneath her hand grew warm.",
    ],
  },
  {
    head: "Chapter 4",
    title: "Starfall",
    paras: [
      "At three in the morning the meteors came all at once, a hundred a minute, and every book in the archive opened by itself.",
      "Thousands of voices filled the dome: poets and sailors, scientists and grandmothers, each reading the line they had waited longest to say.",
    ],
  },
  {
    head: "Starfall",
    paras: [
      "Asha stood in the middle of it with the old book against her chest and listened until she could pick out one voice from all the others.",
      "“Read me the missing page,” she said.",
      "And for the first time in forty years, it was read.",
    ],
  },
  {
    head: "Epilogue",
    title: "Every Story Has a Voice",
    paras: [
      "In the morning the archive was quiet again, the books shelved and closed, the dome full of ordinary light.",
      "Asha wrote the missing page out by hand, as well as she could remember it, and tucked it between chapters thirty-nine and forty.",
    ],
  },
  {
    head: "Every Story Has a Voice",
    paras: [
      "Some nights, at 11:11, she still hears it reading: patient, unhurried, a little amused.",
      "She never tells anyone. She simply climbs the brass ladder, sits on the top rung, and listens, the way a child listens to a story she already knows by heart.",
    ],
  },
];

function StoryPage({ page, folio, side }: { page: (typeof STORY)[number]; folio: number; side: "l" | "r" }) {
  return (
    <>
      <div className="bp-runhead">{page.title ? BOOK_TITLE : page.head}</div>
      {page.title && (
        <>
          <div className="bp-chapter-no bp-tight">{page.head}</div>
          <div className="bp-chapter-title bp-small">{page.title}</div>
        </>
      )}
      {page.paras.map((p, i) => (
        <p key={i} className={i === 0 && page.title ? "bp-p bp-first" : "bp-p"}>
          {p}
        </p>
      ))}
      <Folio n={folio} side={side} />
    </>
  );
}

/** The opening words, as printed (the demo narrates these same sentences). */
const OPENING = [
  "At 11:11 p.m., the oldest book in the Starlight Archive began to read itself aloud. Asha Rao had worked the night shift for three hundred and twelve nights, and nothing in the archive had ever spoken before.",
  "The voice came from the top shelf, soft and unhurried, the way her grandmother used to read to her during monsoon power cuts. She climbed the brass ladder with a torch between her teeth. On the open page, one sentence was glowing, and it was about her.",
];

function TitlePage() {
  return (
    <div className="bp-titlepage">
      <div className="bp-title">{BOOK_TITLE}</div>
      <div className="bp-ornament" aria-hidden>
        * * *
      </div>
      <div className="bp-byline">{BOOK_AUTHOR}</div>
      <div className="bp-imprint">Narrated by VOXORA</div>
    </div>
  );
}

function OpeningPage() {
  return (
    <>
      <div className="bp-runhead">{BOOK_TITLE}</div>
      {OPENING.map((p, i) => (
        <p key={i} className={i === 0 ? "bp-p bp-first" : "bp-p"}>
          {p}
        </p>
      ))}
      <Folio n={3} side="r" />
    </>
  );
}

/**
 * Leafing through the book from the beginning: the cover opens on the title page,
 * then Chapter 1, then the rest of the story, two pages at a time.
 */
export const RIFFLE: Spread[] = [
  { key: "riffle-title", left: <div className="bp-endpaper" />, right: <TitlePage /> },
  { key: "riffle-ch1", left: <ChapterOpener />, right: <OpeningPage /> },
  ...Array.from({ length: STORY.length / 2 }, (_, i) => ({
    key: `riffle-${i}`,
    left: <StoryPage page={STORY[i * 2]} folio={8 + i * 2} side="l" />,
    right: <StoryPage page={STORY[i * 2 + 1]} folio={9 + i * 2} side="r" />,
  })),
];

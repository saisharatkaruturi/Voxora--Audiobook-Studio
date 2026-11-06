import { ArrowRight, AudioLines, BookOpen, Bookmark, Headphones, Languages, Lock, MessagesSquare, ScanText, Users } from "lucide-react";
import { BrandWordmark, Logo } from "@/components/brand/BrandWordmark";
import { BookShowcase } from "@/features/landing/BookShowcase";
import { FloatingCapsule } from "@/components/ui/FloatingCapsule";
import { MiniWaveform } from "@/components/audio/AudioWaveform";
import { ButtonLink } from "@/components/ui/Button";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { brand } from "@/config/brand";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useAuth } from "@/stores/auth";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ShelfCard } from "@/components/book/ShelfCard";
import { reveal, stagger } from "@/config/motion";
import { booksApi } from "@/services/api";
import { Mic2, UploadCloud } from "lucide-react";

const FEATURES = [
  { icon: ScanText, title: "Reads any book", body: "PDF, EPUB, DOCX, TXT, even scanned pages. Scans are recognized and read automatically." },
  { icon: BookOpen, title: "Finds the real chapters", body: "Headings, numbering and tables of contents become a clean chapter list you can refine." },
  { icon: AudioLines, title: "Natural narration", body: "Neural voices that run on your own machine, or cloud voices when you choose them." },
  { icon: Users, title: "A cast of voices", body: "Optional multi-voice mode gives each character a voice, without changing a word of the story." },
  { icon: MessagesSquare, title: "Ask the book", body: "“What happened in chapter five?” Answers cite the passages and keep the text apart from interpretation." },
  { icon: Lock, title: "Private by default", body: "Your books stay yours. You always see where a file is processed, and can delete anything, any time." },
];

export default function LandingPage() {
  const signedIn = !!useAuth((s) => s.token);
  useDocumentTitle(null);
  const cont = useQuery({ queryKey: ["continue"], queryFn: booksApi.continueListening, enabled: signedIn });
  return (
    <div className="relative overflow-x-clip">
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[720px] bg-[radial-gradient(60%_60%_at_70%_20%,rgb(185_241_47/0.10),transparent_70%),radial-gradient(40%_40%_at_85%_55%,rgb(64_160_210/0.10),transparent_70%)]" />
      {/* Top of the page, pinned while scrolling: a short glass bar with the logo on the left,
          and Sign in / Create account as their own buttons in the top-right corner. */}
      <header className="sticky top-3 z-50 mx-auto flex max-w-6xl items-center justify-between gap-3 px-3 sm:px-6">
        <div className="glass flex min-w-0 flex-1 items-center justify-between gap-2 rounded-full py-1.5 pr-1.5 pl-4 sm:pl-5">
          <Logo to="/" className="max-sm:[&>span]:hidden" />
          <ThemeToggle />
        </div>
        <nav className="flex items-center gap-2" aria-label="Account">
          {signedIn && (
            <ButtonLink to="/library" variant="secondary" size="sm" className="glass max-md:hidden">
              Open library
            </ButtonLink>
          )}
          <ButtonLink to="/signin" variant="secondary" size="sm" className="glass">
            Sign in
          </ButtonLink>
          <ButtonLink to="/register" variant="primary" size="sm">
            Create account
          </ButtonLink>
        </nav>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl items-center gap-6 px-5 pt-10 pb-10 sm:px-8 lg:grid-cols-[1fr_1.1fr] lg:pt-6">
          <div className="animate-fade-up">
            <p className="eyebrow mb-6 text-mint-400/90">
              {brand.name} · {brand.descriptor}
            </p>
            <h1 className="font-display text-[3rem] leading-[1.02] font-semibold tracking-tight text-paper-50 sm:text-7xl">
              Your books.
              <br />
              <span className="bg-gradient-to-r from-orchid-400 via-orchid-300 to-mint-400 bg-clip-text text-transparent">Now alive.</span>
            </h1>
            <p className="mt-6 max-w-lg text-lg leading-relaxed text-paper-300">Transform your books and documents into immersive audiobooks with natural AI narration.</p>
            <div className="mt-9 flex flex-wrap gap-3">
              <ButtonLink to="/create" variant="primary" size="lg" icon={<AudioLines className="size-4" />}>
                Create Audiobook
              </ButtonLink>
              <ButtonLink to="/library" variant="secondary" size="lg">
                Explore Library <ArrowRight className="size-4" />
              </ButtonLink>
            </div>
          </div>
          <div className="relative -mx-5 h-[440px] sm:h-[520px] lg:mx-0 lg:h-[600px]">
            <BookShowcase className="absolute inset-0 pb-2" />
            <FloatingCapsule eyebrow="Narration" className="top-[6%] left-[2%] max-sm:hidden" icon={<MiniWaveform active className="w-10" />}>
              Neural voice · 1.0×
            </FloatingCapsule>
            <FloatingCapsule eyebrow="Chapters" className="top-[10%] right-[0%] max-sm:hidden" delay={1.8}>
              Found automatically
            </FloatingCapsule>
            <FloatingCapsule eyebrow="Read-along" className="bottom-[18%] left-[4%] max-sm:hidden" delay={3.2}>
              Every sentence, in sync
            </FloatingCapsule>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-5 pb-20 text-center sm:px-8" aria-label={brand.name}>
          <BrandWordmark size="lg" />
          <p className="mt-3 font-serif text-xl text-paper-300 italic">{brand.tagline}</p>
        </section>

        {signedIn && (cont.data?.items.length ?? 0) > 0 && (
          <motion.section variants={reveal} initial="hidden" whileInView="show" viewport={{ once: true, margin: "-80px" }} className="mx-auto max-w-6xl px-5 pb-24 sm:px-8" aria-labelledby="continue">
            <div className="mb-6 flex items-end justify-between">
              <h2 id="continue" className="font-display text-3xl font-semibold tracking-tight text-paper-50">
                Continue listening
              </h2>
              <ButtonLink to="/library" variant="ghost" size="sm">
                Library <ArrowRight className="size-4" />
              </ButtonLink>
            </div>
            <div className="grid grid-cols-2 gap-5 sm:grid-cols-3 lg:grid-cols-5">
              {cont.data!.items.slice(0, 5).map((b) => (
                <ShelfCard key={b.id} book={b} />
              ))}
            </div>
          </motion.section>
        )}

        <section className="mx-auto max-w-6xl px-5 pb-24 sm:px-8" aria-labelledby="how">
          <motion.h2 variants={reveal} initial="hidden" whileInView="show" viewport={{ once: true }} id="how" className="font-display text-3xl font-semibold tracking-tight text-paper-50 sm:text-5xl">
            How {brand.name} works
          </motion.h2>
          <motion.ol variants={stagger(0.12)} initial="hidden" whileInView="show" viewport={{ once: true, margin: "-60px" }} className="mt-10 grid gap-4 md:grid-cols-3">
            {(
              [
                ["01", "Bring your book", "Drop a PDF, EPUB, DOCX or TXT, even scans. Chapters are found for you.", UploadCloud],
                ["02", "Give it a voice", "Audition narrators, tune the pace, or cast every character.", Mic2],
                ["03", "Start listening", "Chapter by chapter, with read-along and your place remembered.", Headphones],
              ] as const
            ).map(([n, title, body, Icon]) => (
              <motion.li key={n} variants={reveal} className="surface relative overflow-hidden p-7">
                <span className="absolute -top-4 right-4 font-display text-8xl font-semibold text-white/[0.04]" aria-hidden>
                  {n}
                </span>
                <span className="neo flex size-11 items-center justify-center rounded-2xl text-orchid-300">
                  <Icon className="size-5" aria-hidden />
                </span>
                <p className="mt-6 text-xs font-semibold tracking-[0.2em] text-mint-400">{n}</p>
                <h3 className="mt-2 font-display text-xl font-semibold text-paper-50">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-paper-400">{body}</p>
              </motion.li>
            ))}
          </motion.ol>
        </section>

        <section className="mx-auto max-w-6xl px-5 pb-24 sm:px-8" aria-labelledby="features">
          <h2 id="features" className="sr-only">
            Features
          </h2>
          <ol className="mb-10 flex flex-wrap items-center justify-center gap-3 text-xs font-semibold tracking-[0.2em] text-paper-400 uppercase" aria-label="How it works">
            {["Book", "Voice", "Sound", "Immersion"].map((s, i) => (
              <li key={s} className="flex items-center gap-3">
                <span className={i === 3 ? "text-mint-400" : ""}>{s}</span>
                {i < 3 && <ArrowRight className="size-3.5 text-orchid-400" aria-hidden />}
              </li>
            ))}
          </ol>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(({ icon: Icon, title, body }, i) => (
              <div key={title} className="surface animate-fade-up p-6" style={{ animationDelay: `${i * 60}ms` }}>
                <Icon className="size-5 text-orchid-400" aria-hidden />
                <h3 className="mt-4 font-medium text-paper-50">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-paper-400">{body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-5 pb-24 sm:px-8">
          <div className="surface grid gap-8 overflow-hidden p-8 sm:p-12 md:grid-cols-[1fr_auto] md:items-center">
            <div>
              <h2 className="font-display text-3xl font-semibold tracking-tight text-paper-50">{brand.taglines.beyondThePage}</h2>
              <p className="mt-3 max-w-xl text-paper-400">
                Pick up exactly where you stopped, on any device. Speeds from 0.75× to 2×, a sleep timer that fades out gently, bookmarks with notes, and read-along
                highlighting that follows the voice.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-sm text-paper-300">
              {(
                [
                  [Headphones, "Resume anywhere"],
                  [Bookmark, "Bookmarks"],
                  [Languages, "Indian & world languages"],
                ] as const
              ).map(([I, label]) => (
                <span key={label} className="inline-flex items-center gap-2 rounded-full border border-white/[0.08] bg-white/[0.03] px-3.5 py-2">
                  <I className="size-4 text-mint-400" aria-hidden /> {label}
                </span>
              ))}
            </div>
          </div>
        </section>
        <motion.section variants={reveal} initial="hidden" whileInView="show" viewport={{ once: true }} className="mx-auto max-w-6xl px-5 pb-28 text-center sm:px-8">
          <h2 className="font-display text-4xl font-semibold tracking-tight text-paper-50 sm:text-6xl">Your next story is waiting.</h2>
          <ButtonLink to="/create" variant="primary" size="lg" className="mt-8" icon={<AudioLines className="size-4" />}>
            Create Audiobook
          </ButtonLink>
        </motion.section>
      </main>
      <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 border-t border-white/[0.05] px-5 py-8 text-xs text-paper-500 sm:px-8">
        <span>
          {brand.name} · {brand.tagline}
        </span>
        <span>{brand.name} doesn't remove DRM or download books. Bring books you own or may use.</span>
      </footer>
    </div>
  );
}

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { Book, Chapter } from "@/types/api";

const listSpy = vi.fn();
vi.mock("@/services/api", () => ({
  booksApi: {
    list: (q: unknown) => listSpy(q),
    continueListening: () => Promise.resolve({ items: [] }),
  },
  playerApi: { playback: vi.fn(), saveProgress: vi.fn(() => Promise.resolve({})) },
  systemApi: { preferences: vi.fn(() => Promise.resolve({ playback_rate: 1 })) },
}));

function wrap(ui: ReactNode, path = "/library") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const book = (over: Partial<Book>): Book =>
  ({
    id: "b1", title: "The Lantern at Gull Point", subtitle: null, author: "VOXORA Contributors", narrator: "Lessac (Piper)", description: null,
    genre: null, year: null, language: "en", languages: ["en"], status: "ready", source_format: "pdf", page_count: 10, word_count: 800,
    char_count: 4000, ocr_used: false, ocr_engine: null, ocr_confidence: null, warnings: [], cover_url: null, cover_source: null,
    narration: {} as Book["narration"], total_duration: 600, error: null, chapter_count: 9, chapters_with_audio: 7, narrated_chapters: 7,
    progress: null, active_job: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...over,
  }) as Book;

describe("Library", () => {
  it("shows books and filters by status", async () => {
    listSpy.mockResolvedValue({ items: [book({}), book({ id: "b2", title: "Second Book", status: "review", chapters_with_audio: 0 })], total: 2 });
    const { default: LibraryPage } = await import("@/pages/LibraryPage");
    wrap(<LibraryPage />);
    expect((await screen.findAllByText("Second Book")).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Your Library" })).toBeInTheDocument();
    expect(screen.getByLabelText("Play The Lantern at Gull Point")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Draft" }));
    await waitFor(() => expect(listSpy).toHaveBeenLastCalledWith(expect.objectContaining({ status: "review" })));
  });

  it("shows a designed empty state", async () => {
    listSpy.mockResolvedValue({ items: [], total: 0 });
    const { default: LibraryPage } = await import("@/pages/LibraryPage");
    wrap(<LibraryPage />);
    expect(await screen.findByText("Your next story starts here.")).toBeInTheDocument();
  });
});

const chapter = (id: string, title: string, position: number): Chapter =>
  ({ id, book_id: "b1", position, title, kind: "chapter", include_in_audio: true, word_count: 100, char_count: 500, language: "en", audio_status: "pending", audio_progress: 0, audio_error: null, duration: null, stale: false, detection: {}, pages: null, text_version: 1, audio: null }) as Chapter;

describe("Book editor chapter list", () => {
  it("reorders with keyboard-accessible buttons and merges selected chapters", async () => {
    const { ChapterList } = await import("@/features/editor/ChapterList");
    const onReorder = vi.fn();
    const onMerge = vi.fn();
    const chapters = [chapter("a", "One", 0), chapter("b", "Two", 1), chapter("c", "Three", 2)];
    wrap(<ChapterList chapters={chapters} selectedId="a" onSelect={() => {}} onReorder={onReorder} onMerge={onMerge} busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Move Two up" }));
    expect(onReorder).toHaveBeenCalledWith(["b", "a", "c"]);
    await userEvent.click(screen.getByLabelText("Select One for merging"));
    await userEvent.click(screen.getByLabelText("Select Two for merging"));
    await userEvent.click(screen.getByRole("button", { name: "Merge" }));
    expect(onMerge).toHaveBeenCalledWith(["a", "b"]);
  });
});

describe("Player chapter navigation", () => {
  it("jumps to a chapter from the chapter list", async () => {
    const { usePlayer } = await import("@/stores/player");
    const { ChaptersPanel } = await import("@/features/player/SidePanels");
    const selectTrack = vi.fn();
    usePlayer.setState({
      playback: {
        book: { id: "b1", title: "B", author: null, narrator: null, cover_url: null, language: "en" },
        tracks: [
          { chapter_id: "c1", position: 0, title: "Opening", kind: "chapter", url: "/m/1", duration: 60, offset: 0, timing_source: null },
          { chapter_id: "c2", position: 1, title: "The Letter", kind: "chapter", url: "/m/2", duration: 90, offset: 60, timing_source: null },
        ],
        total_duration: 150,
        progress: null,
        bookmarks: [],
      },
      trackIndex: 0,
      selectTrack,
    });
    wrap(<ChaptersPanel />);
    const list = screen.getByRole("list", { name: "Chapters" });
    await userEvent.click(within(list).getByText("The Letter"));
    expect(selectTrack).toHaveBeenCalledWith(1, 0, true);
  });
});

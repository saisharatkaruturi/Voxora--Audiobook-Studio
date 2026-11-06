import { useRef } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, AudioLines, BookOpenText, Headphones, LayoutGrid, MessagesSquare, Mic2, Users } from "lucide-react";
import { booksApi } from "@/services/api";
import { qk } from "@/services/queryClient";
import { useLiveSocket } from "@/hooks/useLiveSocket";
import { Notice, PageLoader } from "@/components/ui/Feedback";
import { ButtonLink } from "@/components/ui/Button";
import { errorMessage } from "@/services/http";
import type { Book, BookSnapshot } from "@/types/api";
import { cn } from "@/utils/format";

export interface BookContext {
  book: Book;
  live: BookSnapshot | null;
}

export function useBookContext() {
  return useOutletContext<BookContext>();
}

const TABS = [
  { to: "", label: "Overview", icon: LayoutGrid, end: true },
  { to: "processing", label: "Progress", icon: AudioLines },
  { to: "edit", label: "Editor", icon: BookOpenText },
  { to: "voice", label: "Voice Studio", icon: Mic2 },
  { to: "cast", label: "AI Cast", icon: Users },
  { to: "ask", label: "Ask the Book", icon: MessagesSquare },
];

export function BookLayout() {
  const { bookId = "" } = useParams();
  const qc = useQueryClient();
  const book = useQuery({ queryKey: qk.book(bookId), queryFn: () => booksApi.get(bookId) });
  const lastKey = useRef<string>("");

  // Live updates: when status, job state or any chapter's audio status changes, refresh dependent data.
  const { data: live } = useLiveSocket<BookSnapshot>(bookId ? `/ws/books/${bookId}` : null, (snap) => {
    const key = JSON.stringify([snap.book.status, snap.job?.status, snap.job?.id, snap.chapters.map((c) => c.audio_status + c.id)]);
    if (key !== lastKey.current) {
      const first = lastKey.current === "";
      lastKey.current = key;
      if (!first) {
        void qc.invalidateQueries({ queryKey: qk.book(bookId) });
        void qc.invalidateQueries({ queryKey: qk.chapters(bookId) });
        void qc.invalidateQueries({ queryKey: qk.playback(bookId) });
        void qc.invalidateQueries({ queryKey: qk.downloads(bookId) });
        void qc.invalidateQueries({ queryKey: ["books"] });
      }
    }
  });

  if (book.isPending) return <PageLoader label="Opening your story" />;
  if (book.isError || !book.data) {
    return (
      <div className="mx-auto max-w-lg pt-10">
        <Notice kind="error" title="This book couldn't be opened" action={<ButtonLink to="/library" size="sm">Library</ButtonLink>}>
          {errorMessage(book.error)}
        </Notice>
      </div>
    );
  }
  const b = book.data;
  const ready = b.status === "ready" || (b.chapters_with_audio ?? 0) > 0;
  return (
    <div className="animate-fade-up">
      <div className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-3">
        <Link to="/library" className="inline-flex items-center gap-1.5 rounded-lg text-sm text-paper-400 hover:text-paper-100">
          <ArrowLeft className="size-4" aria-hidden /> Library
        </Link>
        <span className="text-paper-500" aria-hidden>/</span>
        <span className="max-w-[50vw] truncate text-sm text-paper-200">{b.title}</span>
        {ready && (
          <ButtonLink to={`/books/${b.id}/listen`} size="sm" variant="primary" className="ml-auto" icon={<Headphones className="size-4" />}>
            Listen
          </ButtonLink>
        )}
      </div>
      <nav aria-label="Book sections" className="-mx-4 mb-8 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <div className="inline-flex min-w-full gap-1 border-b border-white/[0.06]">
          {TABS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={label}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "relative -mb-px inline-flex h-11 items-center gap-2 border-b-2 px-3 text-sm font-medium whitespace-nowrap transition-colors",
                  isActive ? "border-orchid-500 text-paper-50" : "border-transparent text-paper-400 hover:text-paper-100",
                )
              }
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </NavLink>
          ))}
        </div>
      </nav>
      <Outlet context={{ book: b, live } satisfies BookContext} />
    </div>
  );
}

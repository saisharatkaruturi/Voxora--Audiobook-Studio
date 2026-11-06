import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AudioLines, Bell, Check, Compass, Library, Loader2, LogOut, Plus, Search, Settings, ShieldCheck, X } from "lucide-react";
import { BrandMark } from "@/components/brand/BrandMark";
import { Logo } from "@/components/brand/BrandWordmark";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { jobsApi, systemApi } from "@/services/api";
import { useAuth } from "@/stores/auth";
import { usePlayer } from "@/stores/player";
import type { Job } from "@/types/api";
import { cn, relativeTime } from "@/utils/format";

export const NAV_ITEMS = [
  { to: "/library", label: "Library", icon: Library },
  { to: "/create", label: "Create", icon: Plus },
  { to: "/discover", label: "Discover", icon: Compass },
  { to: "/studio", label: "Studio", icon: AudioLines },
];

function useScrolled(threshold = 12) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > threshold);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, [threshold]);
  return scrolled;
}

/** Floating glass navigation: compacts and blurs more once the page scrolls. */
export function Navbar() {
  const scrolled = useScrolled();
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement)?.tagName);
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <header className={cn("fixed inset-x-0 top-0 z-40 flex justify-center px-3 transition-[padding] duration-500 ease-[var(--ease-out-soft)]", scrolled ? "pt-2" : "pt-4")}>
        <nav
          aria-label="Main"
          className={cn(
            "glass flex w-full max-w-5xl items-center gap-2 rounded-full pr-2 pl-4 shadow-[0_12px_40px_-12px_rgb(0_0_0/0.8),inset_0_1px_0_rgb(255_255_255/0.07)] transition-all duration-500 ease-[var(--ease-out-soft)]",
            scrolled ? "h-12 bg-ink-850/80 backdrop-blur-2xl" : "h-14",
          )}
        >
          <Logo compact className="shrink-0" />
          <div className="mx-auto hidden items-center gap-1 md:flex">
            {NAV_ITEMS.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    "relative rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors duration-300",
                    isActive
                      ? "bg-white/[0.08] text-paper-50 shadow-[inset_0_1px_0_rgb(255_255_255/0.08),0_0_20px_-6px_rgb(196_92_255/0.6)]"
                      : "text-paper-400 hover:text-paper-100",
                  )
                }
              >
                {label}
              </NavLink>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-0.5 md:ml-0">
            <span className="mx-2 hidden h-5 w-px bg-white/10 md:block" aria-hidden />
            <NavIcon label="Search (Ctrl K)" onClick={() => setSearchOpen(true)}>
              <Search className="size-4" />
            </NavIcon>
            <ThemeToggle />
            <Activity />
            <ProfileMenu />
          </div>
        </nav>
      </header>
      {searchOpen && <SearchPalette onClose={() => setSearchOpen(false)} />}
    </>
  );
}

/** Bottom tab bar on phones. */
export function MobileTabs() {
  return (
    <nav aria-label="Main" className="glass fixed inset-x-0 bottom-0 z-40 flex h-[calc(64px+env(safe-area-inset-bottom))] items-start justify-around border-x-0 border-b-0 pt-1.5 pb-[env(safe-area-inset-bottom)] md:hidden">
      {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
        <NavLink key={to} to={to} className={({ isActive }) => cn("flex min-w-16 flex-col items-center gap-1 rounded-xl px-2 py-1.5 text-[11px] font-medium", isActive ? "text-orchid-400" : "text-paper-400")}>
          <Icon className="size-5" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

function NavIcon({ label, onClick, children, active }: { label: string; onClick: () => void; children: ReactNode; active?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn("relative flex size-9 items-center justify-center rounded-full text-paper-300 transition-colors hover:bg-white/[0.07] hover:text-paper-50", active && "bg-white/[0.07] text-paper-50")}
    >
      {children}
    </button>
  );
}

function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  return { open, setOpen, ref };
}

const JOB_LABEL: Record<string, string> = {
  analyze: "Reading the pages",
  generate_book: "Creating the audiobook",
  generate_chapter: "Regenerating a chapter",
  index_book: "Preparing Ask the Book",
  cast_analysis: "Finding the characters",
  insights: "Writing book insights",
  ask: "Answering a question",
  install_voice: "Installing a voice",
};

/** Real background activity (jobs), newest first. */
function Activity() {
  const { open, setOpen, ref } = usePopover();
  const jobs = useQuery({ queryKey: ["activity"], queryFn: () => jobsApi.list({ limit: 8 }), refetchInterval: (q) => (open || q.state.data?.items.some((j) => j.status === "running" || j.status === "queued") ? 4000 : 30000) });
  const items = jobs.data?.items ?? [];
  const running = items.some((j) => j.status === "running" || j.status === "queued");
  return (
    <div ref={ref} className="relative">
      <NavIcon label={running ? "Activity (work in progress)" : "Activity"} onClick={() => setOpen(!open)} active={open}>
        <Bell className="size-4" />
        {running && <span className="absolute top-2 right-2 size-2 animate-pulse-soft rounded-full bg-mint-400" />}
      </NavIcon>
      {open && (
        <div className="glass absolute top-12 right-0 w-80 animate-fade-up rounded-2xl p-2 shadow-2xl" role="dialog" aria-label="Activity">
          <p className="eyebrow px-3 pt-2 pb-2">Activity</p>
          {items.length === 0 ? (
            <p className="px-3 pb-3 text-sm text-paper-400">Nothing yet. Add a book to begin.</p>
          ) : (
            <ul className="max-h-96 overflow-y-auto">
              {items.map((j) => (
                <li key={j.id}>
                  <Link to={j.book_id ? (j.type.startsWith("generate") || j.type === "analyze" ? `/books/${j.book_id}/processing` : `/books/${j.book_id}`) : "/studio"} onClick={() => setOpen(false)} className="flex items-start gap-3 rounded-xl px-3 py-2.5 hover:bg-white/[0.05]">
                    <JobIcon job={j} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-paper-100">{JOB_LABEL[j.type] ?? j.type}</p>
                      <p className="truncate text-xs text-paper-500">{j.status === "failed" ? j.error?.message : j.message}</p>
                    </div>
                    <span className="shrink-0 text-[11px] text-paper-500">{relativeTime(j.created_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function JobIcon({ job }: { job: Job }) {
  if (job.status === "running" || job.status === "queued") return <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-mint-400" />;
  if (job.status === "completed") return <Check className="mt-0.5 size-4 shrink-0 text-mint-400" />;
  if (job.status === "failed") return <X className="mt-0.5 size-4 shrink-0 text-rose-400" />;
  return <span className="mt-1.5 size-2 shrink-0 rounded-full bg-paper-500" />;
}

function ProfileMenu() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const { open, setOpen, ref } = usePopover();
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label="Account menu"
        aria-expanded={open}
        className="ml-1 flex size-9 items-center justify-center rounded-full bg-orchid-500 text-xs font-semibold text-ink-950 shadow-[0_0_0_2px_var(--page-bg),0_0_0_3px_var(--surface-border)]"
      >
        {user?.display_name?.[0]?.toUpperCase() ?? "·"}
      </button>
      {open && (
        <div className="glass absolute top-12 right-0 w-64 animate-fade-up rounded-2xl p-2 shadow-2xl" role="menu">
          <div className="px-3 pt-2 pb-3">
            <p className="truncate text-sm font-medium text-paper-50">{user?.display_name}</p>
            <p className="truncate text-xs text-paper-500">{user?.email}</p>
          </div>
          <MenuLink to="/settings" icon={<Settings className="size-4" />} onClick={() => setOpen(false)}>
            Settings
          </MenuLink>
          <MenuLink to="/settings#privacy" icon={<ShieldCheck className="size-4" />} onClick={() => setOpen(false)}>
            Privacy & data
          </MenuLink>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              usePlayer.getState().close();
              signOut();
              navigate("/");
            }}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-paper-300 hover:bg-white/[0.05] hover:text-rose-400"
          >
            <LogOut className="size-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function MenuLink({ to, icon, children, onClick }: { to: string; icon: ReactNode; children: ReactNode; onClick: () => void }) {
  return (
    <Link to={to} role="menuitem" onClick={onClick} className="flex items-center gap-3 rounded-xl px-3 py-2 text-sm text-paper-300 hover:bg-white/[0.05] hover:text-paper-50">
      {icon}
      {children}
    </Link>
  );
}

/** Ctrl/Cmd+K: jump to any book or chapter. */
function SearchPalette({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const navigate = useNavigate();
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 180);
    return () => clearTimeout(t);
  }, [q]);
  const res = useQuery({ queryKey: ["search", debounced], queryFn: () => systemApi.search(debounced), enabled: debounced.length > 1 });
  const go = (to: string) => {
    onClose();
    navigate(to);
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);
  const results = [
    ...(res.data?.books ?? []).map((b) => ({ key: `b${b.id}`, to: `/books/${b.id}`, title: b.title, sub: b.author ?? "Book" })),
    ...(res.data?.chapters ?? []).map((c) => ({ key: `c${c.id}`, to: `/books/${c.book_id}/edit`, title: c.title, sub: c.book_title })),
  ];
  return (
    <div className="fixed inset-0 z-[80] flex items-start justify-center bg-black/50 px-4 pt-[14vh] backdrop-blur-sm" onMouseDown={onClose} role="dialog" aria-modal="true" aria-label="Search">
      <div className="glass w-full max-w-xl animate-fade-up overflow-hidden rounded-3xl shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-white/[0.06] px-5">
          <Search className="size-4 text-paper-500" />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && results[0] && go(results[0].to)}
            placeholder="Search titles, authors and chapters"
            aria-label="Search titles, authors and chapters"
            className="h-14 flex-1 bg-transparent text-[15px] text-paper-50 placeholder:text-paper-500 focus:outline-none"
          />
          <kbd className="rounded-md border border-white/10 px-1.5 py-0.5 text-[10px] text-paper-500">Esc</kbd>
        </div>
        <ul className="max-h-[50vh] overflow-y-auto p-2">
          {debounced.length < 2 ? (
            <li className="flex items-center gap-3 px-3 py-6 text-sm text-paper-500">
              <BrandMark className="size-5" /> Type to search your library.
            </li>
          ) : res.isPending ? (
            <li className="px-3 py-6 text-sm text-paper-500">Searching…</li>
          ) : results.length === 0 ? (
            <li className="px-3 py-6 text-sm text-paper-500">No books or chapters match “{debounced}”.</li>
          ) : (
            results.map((r) => (
              <li key={r.key}>
                <button type="button" onClick={() => go(r.to)} className="flex w-full flex-col rounded-xl px-3 py-2.5 text-left hover:bg-white/[0.06] focus-visible:bg-white/[0.06]">
                  <span className="text-sm text-paper-50">{r.title}</span>
                  <span className="text-xs text-paper-500">{r.sub}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}

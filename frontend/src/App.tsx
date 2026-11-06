import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { BookLayout } from "@/features/book/BookLayout";
import { PageLoader } from "@/components/ui/Feedback";
import { Toaster } from "@/components/ui/Toast";
import { Ambient } from "@/components/layout/Ambient";
import { ConnectionBanner } from "@/components/layout/ConnectionBanner";

// The front door loads with the app, not after it: no loading screen before the first page.
import LandingPage from "@/pages/LandingPage";
const AuthPage = lazy(() => import("@/pages/AuthPage"));
const LibraryPage = lazy(() => import("@/pages/LibraryPage"));
const UploadPage = lazy(() => import("@/pages/UploadPage"));
const ProcessingPage = lazy(() => import("@/pages/ProcessingPage"));
const BookDetailsPage = lazy(() => import("@/pages/BookDetailsPage"));
const EditorPage = lazy(() => import("@/pages/EditorPage"));
const VoiceStudioPage = lazy(() => import("@/pages/VoiceStudioPage"));
const CastPage = lazy(() => import("@/pages/CastPage"));
const PlayerPage = lazy(() => import("@/pages/PlayerPage"));
const AskPage = lazy(() => import("@/pages/AskPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));
const NotFoundPage = lazy(() => import("@/pages/NotFoundPage"));
const DiscoverPage = lazy(() => import("@/pages/DiscoverPage"));
const StudioPage = lazy(() => import("@/pages/StudioPage"));

export function App() {
  return (
    <>
      <Ambient />
      <Toaster />
      <ConnectionBanner />
      <Suspense fallback={<PageLoader label="Opening VOXORA" />}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/signin" element={<AuthPage mode="signin" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route element={<RequireAuth />}>
            <Route element={<AppShell />}>
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/create" element={<UploadPage />} />
              <Route path="/upload" element={<Navigate to="/create" replace />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/discover" element={<DiscoverPage />} />
              <Route path="/studio" element={<StudioPage />} />
              <Route path="/books/:bookId/listen" element={<PlayerPage />} />
              <Route path="/books/:bookId" element={<BookLayout />}>
                <Route index element={<BookDetailsPage />} />
                <Route path="processing" element={<ProcessingPage />} />
                <Route path="edit" element={<EditorPage />} />
                <Route path="voice" element={<VoiceStudioPage />} />
                <Route path="cast" element={<CastPage />} />
                <Route path="ask" element={<AskPage />} />
              </Route>
              <Route path="/books" element={<Navigate to="/library" replace />} />
              {/* Short aliases */}
              <Route path="/book/:bookId" element={<Alias to="" />} />
              <Route path="/player/:bookId" element={<Alias to="/listen" />} />
              <Route path="/ask/:bookId" element={<Alias to="/ask" />} />
              <Route path="/voice-studio/:bookId" element={<Alias to="/voice" />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Route>
        </Routes>
      </Suspense>
    </>
  );
}

function Alias({ to }: { to: string }) {
  const { bookId } = useParams();
  return <Navigate to={`/books/${bookId}${to}`} replace />;
}

import { useEffect } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { authApi } from "@/services/api";
import { useAuth } from "@/stores/auth";
import { PageLoader, Notice } from "@/components/ui/Feedback";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/services/http";

export function RequireAuth() {
  const { token, user, setUser, signOut } = useAuth();
  const location = useLocation();
  const me = useQuery({ queryKey: ["me", token], queryFn: authApi.me, enabled: !!token && !user, staleTime: Infinity });

  useEffect(() => {
    if (me.data) setUser(me.data);
  }, [me.data, setUser]);

  if (!token) return <Navigate to="/signin" replace state={{ from: location.pathname + location.search }} />;
  if (!user && me.isError) {
    return (
      <div className="mx-auto max-w-md p-8">
        <Notice kind="error" title="Couldn't load your account" action={
            <div className="flex gap-2">
              <Button size="sm" onClick={() => void me.refetch()}>
                Retry
              </Button>
              <Button size="sm" variant="ghost" onClick={signOut}>
                Sign out
              </Button>
            </div>
          }>
          {errorMessage(me.error)}
        </Notice>
      </div>
    );
  }
  if (!user) return <PageLoader label="Opening your library" />;
  return <Outlet />;
}

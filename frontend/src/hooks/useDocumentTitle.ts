import { useEffect } from "react";
import { pageTitle } from "@/config/brand";

/** Sets the tab title in the consistent "VOXORA · Section" format. */
export function useDocumentTitle(section?: string | null) {
  useEffect(() => {
    document.title = pageTitle(section);
  }, [section]);
}

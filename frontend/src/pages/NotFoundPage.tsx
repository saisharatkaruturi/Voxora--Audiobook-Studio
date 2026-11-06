import { Compass } from "lucide-react";
import { EmptyState } from "@/components/ui/Feedback";
import { ButtonLink } from "@/components/ui/Button";

export default function NotFoundPage() {
  return (
    <div className="mx-auto max-w-xl pt-10">
      <EmptyState icon={<Compass className="size-6" />} title="This page isn't in the library" action={<ButtonLink to="/library" variant="primary">Back to library</ButtonLink>}>
        The link may be outdated, or the book was deleted.
      </EmptyState>
    </div>
  );
}

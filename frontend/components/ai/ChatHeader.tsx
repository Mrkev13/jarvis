import { JarvisAvatar } from "@/components/jarvis/JarvisAvatar";
import { Button, HudLabel, StatusPulse } from "@/components/ui";
import type { JarvisState } from "@/lib/jarvisAvatar";

/**
 * Hlavička chatu: jediné h1 stránky, název aktivní konverzace. Pod lg otevírá konverzace v Draweru
 * a nabízí „Nový chat" (na širokém displeji jsou obě akce v postranním panelu).
 */
export function ChatHeader({
  title,
  onOpenConversations,
  conversationsOpen,
  onNew,
  creating,
  jarvisState,
}: {
  title: string | null;
  onOpenConversations: () => void;
  conversationsOpen: boolean;
  onNew: () => void;
  creating: boolean;
  jarvisState: JarvisState;
}) {
  return (
    <header className="border-b border-line">
      <div className="mx-auto flex w-full max-w-4xl items-center gap-3 px-4 py-3 md:px-6">
        <JarvisAvatar state={jarvisState} size="sm" className="shadow-[0_0_24px_-12px_rgba(46,220,255,.75)]" />
        <div className="min-w-0 flex-1">
          <HudLabel className="hidden items-center gap-1.5 sm:flex">
            <StatusPulse tone="ai" className="h-1.5 w-1.5" /> Standa AI · asistent
          </HudLabel>
          <h1 className="text-lg font-semibold leading-tight text-ink md:text-xl">AI asistent</h1>
          <p className="truncate text-sm text-ink-muted" title={title ?? undefined}>
            {title ?? "Konverzace s přístupem k tvým datům"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 lg:hidden">
          <Button size="sm" variant="secondary" onClick={onOpenConversations} aria-haspopup="dialog" aria-expanded={conversationsOpen}>
            Konverzace
          </Button>
          <Button size="sm" variant="ghost" onClick={onNew} busy={creating} busyLabel="…" aria-label="Nový chat">
            + Nový
          </Button>
        </div>
      </div>
    </header>
  );
}

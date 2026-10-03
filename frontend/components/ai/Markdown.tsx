import { memo, useMemo } from "react";
import { WeeklyPlanCard } from "@/components/PlannerCards";
import { parseMarkdown, type Inline } from "@/lib/markdown";

function InlineNodes({ nodes }: { nodes: Inline[] }) {
  return (
    <>
      {nodes.map((n, i) =>
        n.type === "code" ? (
          <code key={i} className="rounded border border-line bg-app px-1.5 py-0.5 font-mono text-[0.85em] text-accent-strong">
            {n.text}
          </code>
        ) : n.type === "strong" ? (
          <strong key={i} className="font-semibold text-ink">
            <InlineNodes nodes={n.children ?? []} />
          </strong>
        ) : n.type === "em" ? (
          <em key={i}>
            <InlineNodes nodes={n.children ?? []} />
          </em>
        ) : (
          <span key={i}>{n.text}</span>
        ),
      )}
    </>
  );
}

/**
 * Odpověď AI v Markdownu (parser v lib/markdown.ts). Nadpisy z odpovědi jsou h3/h4 – stránka má jediné h1
 * a konverzace h2. Starší týdenní plán v JSON se vykreslí stejnou kartou jako na stránce Plánovač.
 */
export const Markdown = memo(function Markdown({ content }: { content: string }) {
  const blocks = useMemo(() => parseMarkdown(content), [content]);
  return (
    <div className="space-y-3 break-words text-[15px] leading-7 text-ink-2">
      {blocks.map((b, i) => {
        switch (b.type) {
          case "heading": {
            const Tag = b.level === 1 ? "h3" : "h4";
            return (
              <Tag key={i} className={b.level === 1 ? "pt-1 text-lg font-semibold text-ink" : "pt-1 text-base font-semibold text-ink"}>
                <InlineNodes nodes={b.content} />
              </Tag>
            );
          }
          case "list": {
            const Tag = b.ordered ? "ol" : "ul";
            return (
              <Tag key={i} className={`ml-5 space-y-1 marker:text-ink-faint ${b.ordered ? "list-decimal" : "list-disc"}`}>
                {b.items.map((item, j) => (
                  <li key={j}>
                    <InlineNodes nodes={item} />
                  </li>
                ))}
              </Tag>
            );
          }
          case "code":
            return (
              <pre key={i} className="overflow-x-auto rounded-[var(--radius-control)] border border-line-subtle bg-app p-3 text-sm">
                {b.lang ? <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink-faint">{b.lang}</div> : null}
                <code className="whitespace-pre-wrap font-mono text-ink-2">{b.text}</code>
              </pre>
            );
          case "plan":
            return <WeeklyPlanCard key={i} plan={{ mode: "weekly", summary: b.summary, actions: b.actions }} compact />;
          default:
            return (
              <p key={i}>
                <InlineNodes nodes={b.content} />
              </p>
            );
        }
      })}
    </div>
  );
});

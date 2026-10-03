/**
 * Jednoduchý Markdown odpovědí AI → bloky (Roadmap 4C: logika oddělená od vykreslení, testy markdown.test.mjs).
 * Podporuje: # ## ### nadpisy, odstavce, - / * a 1. seznamy, ``` bloky kódu, `kód`, **tučně**, *kurzíva* / _kurzíva_.
 * Blok ```json s týdenním plánem ({summary, actions[]}) se vrátí jako „plan" (vykreslí se kartou Planneru).
 */
export type Inline = { type: "text" | "code" | "strong" | "em"; text?: string; children?: Inline[] };

export type PlanAction = { priority: number; area: string; title: string; reason: string };

export type Block =
  | { type: "heading"; level: 1 | 2 | 3; content: Inline[] }
  | { type: "paragraph"; content: Inline[] }
  | { type: "list"; ordered: boolean; items: Inline[][] }
  | { type: "code"; lang: string; text: string }
  | { type: "plan"; summary: string; actions: PlanAction[] };

const INLINE_RE = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_)/;

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  for (const tok of text.split(INLINE_RE)) {
    if (!tok) continue;
    if (tok.length > 2 && tok.startsWith("`") && tok.endsWith("`")) out.push({ type: "code", text: tok.slice(1, -1) });
    else if (tok.length > 4 && tok.startsWith("**") && tok.endsWith("**")) out.push({ type: "strong", children: parseInline(tok.slice(2, -2)) });
    else if (tok.length > 2 && ((tok.startsWith("*") && tok.endsWith("*")) || (tok.startsWith("_") && tok.endsWith("_"))))
      out.push({ type: "em", children: parseInline(tok.slice(1, -1)) });
    else out.push({ type: "text", text: tok });
  }
  return out;
}

/** Starší formát: týdenní plán jako JSON v bloku kódu (1–8 akcí s prioritou, oblastí, titulkem a důvodem). */
export function tryParsePlan(raw: string): { summary: string; actions: PlanAction[] } | null {
  try {
    const parsed = JSON.parse(raw) as { summary?: unknown; actions?: unknown };
    if (!parsed || typeof parsed.summary !== "string" || !Array.isArray(parsed.actions)) return null;
    if (parsed.actions.length === 0 || parsed.actions.length > 8) return null;
    for (const a of parsed.actions as Array<Record<string, unknown>>) {
      if (typeof a?.priority !== "number" || typeof a.area !== "string" || typeof a.title !== "string" || typeof a.reason !== "string") return null;
    }
    return { summary: parsed.summary, actions: parsed.actions as PlanAction[] };
  } catch {
    return null;
  }
}

const OL = /^\s*\d+\.\s+(.+)$/;
const UL = /^\s*[-*]\s+(.+)$/;

export function parseMarkdown(content: string): Block[] {
  const lines = content.split(/\r?\n/);
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.trim().startsWith("```")) {
      const lang = line.trim().slice(3).trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) buf.push(lines[i++]);
      if (i < lines.length) i++;
      const plan = lang === "json" || !lang ? tryParsePlan(buf.join("\n")) : null;
      blocks.push(plan ? { type: "plan", ...plan } : { type: "code", lang, text: buf.join("\n") });
      continue;
    }
    const h = /^(#{1,3})\s+(.+)$/.exec(line);
    if (h) {
      blocks.push({ type: "heading", level: h[1].length as 1 | 2 | 3, content: parseInline(h[2]) });
      i++;
      continue;
    }
    const listRe = OL.test(line) ? OL : UL.test(line) ? UL : null;
    if (listRe) {
      const items: Inline[][] = [];
      while (i < lines.length && listRe.test(lines[i])) items.push(parseInline(listRe.exec(lines[i++])![1]));
      blocks.push({ type: "list", ordered: listRe === OL, items });
      continue;
    }
    const buf = [line];
    i++;
    while (i < lines.length && lines[i].trim() && !/^#/.test(lines[i]) && !UL.test(lines[i]) && !OL.test(lines[i]) && !lines[i].trim().startsWith("```")) {
      buf.push(lines[i++]);
    }
    blocks.push({ type: "paragraph", content: parseInline(buf.join(" ")) });
  }
  return blocks;
}

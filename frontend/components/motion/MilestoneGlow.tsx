"use client";

import { useTransitionSignal } from "@/lib/motion";
import { becameTrue } from "@/lib/motionState";
import { cx } from "@/lib/ui";

interface MilestoneGlowProps {
  /** Je milník dosažen (nový rekord, Ace Tanker, splněný cíl…)? */
  reached: boolean;
  /** Data jsou načtená (dokud ne, dosažení se nepočítá jako událost). Výchozí true. */
  ready?: boolean;
  /** Zpráva pro čtečku při dosažení (role=status). Viditelný text dodává obsah. */
  announce?: string;
  children: React.ReactNode;
  as?: "div" | "span" | "li" | "section" | "article";
  className?: string;
}

/**
 * Sémantické primitivum „milník" (Roadmap 6A): dosažený milník má trvalý jemný azurový obrys;
 * v okamžiku dosažení se jednou rozzáří (≤ 1,2 s). Žádné konfety, ohňostroje ani celoobrazovkové efekty.
 * Obrys i záře jsou pseudo-elementy (čtečka je nevidí, nic nepřekrývají pro kliknutí); obrys přebírá
 * zaoblení hostitele (`rounded-*` v className). Omezený pohyb → jen statický obrys.
 */
export function MilestoneGlow({ reached, ready = true, announce, children, as: Tag = "div", className }: MilestoneGlowProps) {
  const signal = useTransitionSignal(reached, ready, becameTrue);
  const justReached = reached && signal > 0;
  return (
    <Tag
      data-milestone={reached ? "true" : "false"}
      className={cx(reached && "motion-milestone", justReached && "motion-milestone-reached", className)}
    >
      {children}
      {announce ? (
        <span role="status" className="sr-only">
          {justReached ? announce : ""}
        </span>
      ) : null}
    </Tag>
  );
}

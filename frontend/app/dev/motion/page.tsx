import { notFound } from "next/navigation";
import { MotionPreview } from "@/components/motion/MotionPreview";

// Vývojová ukázka motion systému. Mimo MOTION_PREVIEW=1 vrací 404 (v běžném provozu neexistuje).
export const dynamic = "force-dynamic";

export default function MotionPreviewPage() {
  if (process.env.MOTION_PREVIEW !== "1") notFound();
  return <MotionPreview />;
}

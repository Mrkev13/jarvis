import { notFound } from "next/navigation";
import { JarvisCompanionPreview } from "@/components/jarvis/JarvisCompanionPreview";

// Vývojová ukázka Jarvis companiona (MRK-16). Stejně jako /dev/motion jen s MOTION_PREVIEW=1, jinak 404.
export const dynamic = "force-dynamic";

export default function JarvisPreviewPage() {
  if (process.env.MOTION_PREVIEW !== "1") notFound();
  return <JarvisCompanionPreview />;
}

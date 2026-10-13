import { Clapperboard, FileText, Smartphone, Sparkles, Upload, type LucideIcon } from "lucide-react";

export type WorkflowStepKey = "upload" | "transcribe" | "detect" | "generate" | "edit";

/** The creator workflow, in order. Shared by the dashboard guide and the project stepper. */
export const WORKFLOW_STEPS: Array<{ key: WorkflowStepKey; label: string; hint: string; icon: LucideIcon }> = [
  { key: "upload", label: "Upload", hint: "Add a long recording", icon: Upload },
  { key: "transcribe", label: "Transcribe", hint: "Timestamped transcript", icon: FileText },
  { key: "detect", label: "Find clips", hint: "AI ranks the best moments", icon: Sparkles },
  { key: "generate", label: "Generate", hint: "Render the moment as a clip", icon: Clapperboard },
  { key: "edit", label: "Edit", hint: "9:16 short with captions", icon: Smartphone },
];

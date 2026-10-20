import { ApiError } from "@/lib/api";
import { listVideoClips, type GeneratedClip } from "@/lib/clips";
import { getProject, isProjectId, type Project } from "@/lib/projects";
import { listProjectVideos } from "@/lib/videos";

/** A project and one of its generated clips (404 for anything the user does not own). */
export async function loadProjectClip(projectId: string, clipId: string): Promise<{ project: Project; clip: GeneratedClip }> {
  if (!isProjectId(projectId) || !isProjectId(clipId)) throw new ApiError(404, "Clip not found");
  const [project, videos] = await Promise.all([getProject(projectId), listProjectVideos(projectId)]);
  for (const video of videos) {
    const page = await listVideoClips(projectId, video.id);
    const clip = page.clips.find((c) => c.id === clipId);
    if (clip) return { project, clip };
  }
  throw new ApiError(404, "Clip not found");
}

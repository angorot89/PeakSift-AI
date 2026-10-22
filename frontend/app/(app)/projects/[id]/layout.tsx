import { ProjectFrame } from "@/components/app/project/project-frame";

/** Every page of one project shares its name and section navigation. */
export default function ProjectLayout({ children }: LayoutProps<"/projects/[id]">) {
  return <ProjectFrame>{children}</ProjectFrame>;
}

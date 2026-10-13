export const metadata = {
  title: "工作台",
  robots: { index: false, follow: false },
};
import { Workspace } from "@/features/workspace";
export default function Layout({ children }: { children: React.ReactNode }) {
  return <Workspace admin>{children}</Workspace>;
}

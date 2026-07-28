import { redirect } from "next/navigation";

// The discovery feed is the core of v1 — make it the landing page.
export default function Home() {
  redirect("/feed");
}

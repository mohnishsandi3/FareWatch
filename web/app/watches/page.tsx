import WatchManager from "@/components/WatchManager";

export const dynamic = "force-dynamic";

export default function WatchesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Your watches</h1>
        <p className="mt-1 text-sm text-gray-500">
          Tell FareWatch what you&rsquo;re after — e.g. &ldquo;anywhere from
          Boston under $400 in the next 3 months&rdquo; — and we&rsquo;ll alert
          you when a real deal appears.
        </p>
      </div>
      <WatchManager />
    </div>
  );
}

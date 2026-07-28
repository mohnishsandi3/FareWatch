"use client";

import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  createWatch,
  deactivateWatch,
  listWatches,
} from "@/lib/api";
import type { Watch, WatchCreate } from "@/lib/types";
import { money, shortDate } from "@/lib/format";

const EMAIL_KEY = "farewatch.email";

const todayISO = () => new Date().toISOString().slice(0, 10);
const plusMonthsISO = (m: number) => {
  const d = new Date();
  d.setMonth(d.getMonth() + m);
  return d.toISOString().slice(0, 10);
};

const emptyForm = (): WatchCreate => ({
  email: "",
  origin: "",
  destination: "",
  max_price: undefined,
  date_window_start: todayISO(),
  date_window_end: plusMonthsISO(3),
  flexible_dates: true,
  cabin: "economy",
});

export default function WatchManager() {
  const [email, setEmail] = useState("");
  const [watches, setWatches] = useState<Watch[]>([]);
  const [form, setForm] = useState<WatchCreate>(emptyForm());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Remember the email locally so the list reloads on revisit (MVP: no auth).
  useEffect(() => {
    const saved = window.localStorage.getItem(EMAIL_KEY);
    if (saved) setEmail(saved);
  }, []);

  const refresh = useCallback(async (addr: string) => {
    if (!addr) return;
    setLoading(true);
    setError(null);
    try {
      setWatches(await listWatches(addr));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load watches");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (email) void refresh(email);
  }, [email, refresh]);

  const onLoad = (e: React.FormEvent) => {
    e.preventDefault();
    window.localStorage.setItem(EMAIL_KEY, email.trim());
    void refresh(email.trim());
  };

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const body: WatchCreate = {
      ...form,
      email: email.trim(),
      origin: form.origin.trim().toUpperCase(),
      destination: form.destination?.trim() ? form.destination.trim().toUpperCase() : null,
      max_price: form.max_price ? Number(form.max_price) : null,
    };
    try {
      await createWatch(body);
      setForm(emptyForm());
      await refresh(email.trim());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to create watch");
    }
  };

  const onDelete = async (id: string) => {
    setError(null);
    try {
      await deactivateWatch(id, email.trim());
      await refresh(email.trim());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to delete watch");
    }
  };

  return (
    <div className="space-y-8">
      <form onSubmit={onLoad} className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-sm">
          <span className="mb-1 text-gray-600">Your email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-72 rounded-lg border border-gray-300 px-3 py-2"
          />
        </label>
        <button className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700">
          Load my watches
        </button>
      </form>

      {error && (
        <div className="rounded-lg bg-conf-low/10 px-4 py-2 text-sm text-conf-low ring-1 ring-conf-low/30">
          {error}
        </div>
      )}

      {email && (
        <section className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="mb-4 text-lg font-semibold">New watch</h2>
          <form onSubmit={onCreate} className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Origin (IATA)">
              <input
                required
                maxLength={3}
                value={form.origin}
                onChange={(e) => setForm({ ...form, origin: e.target.value })}
                placeholder="BOS"
                className="input"
              />
            </Field>
            <Field label="Destination (blank = anywhere)">
              <input
                maxLength={3}
                value={form.destination ?? ""}
                onChange={(e) => setForm({ ...form, destination: e.target.value })}
                placeholder="anywhere"
                className="input"
              />
            </Field>
            <Field label="Max price (USD)">
              <input
                type="number"
                min={1}
                value={form.max_price ?? ""}
                onChange={(e) =>
                  setForm({ ...form, max_price: e.target.value ? Number(e.target.value) : undefined })
                }
                placeholder="400"
                className="input"
              />
            </Field>
            <Field label="From">
              <input
                type="date"
                required
                value={form.date_window_start}
                onChange={(e) => setForm({ ...form, date_window_start: e.target.value })}
                className="input"
              />
            </Field>
            <Field label="To">
              <input
                type="date"
                required
                value={form.date_window_end}
                onChange={(e) => setForm({ ...form, date_window_end: e.target.value })}
                className="input"
              />
            </Field>
            <div className="flex items-end">
              <button className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500">
                Create watch
              </button>
            </div>
          </form>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold">
          Active watches {loading && <span className="text-sm text-gray-400">loading…</span>}
        </h2>
        {watches.length === 0 ? (
          <p className="text-sm text-gray-500">No active watches yet.</p>
        ) : (
          <ul className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white">
            {watches.map((w) => (
              <li key={w.id} className="flex items-center justify-between gap-4 p-4">
                <div className="text-sm">
                  <div className="font-medium text-gray-900">
                    {w.origin} &rarr; {w.destination ?? "anywhere"}
                    {w.max_price != null && (
                      <span className="ml-2 text-gray-500">under {money(w.max_price)}</span>
                    )}
                  </div>
                  <div className="text-gray-500">
                    {shortDate(w.date_window_start)} – {shortDate(w.date_window_end)} ·{" "}
                    {w.flexible_dates ? "flexible dates" : "fixed dates"} · {w.cabin}
                  </div>
                </div>
                <button
                  onClick={() => onDelete(w.id)}
                  className="rounded-lg px-3 py-1.5 text-sm font-medium text-conf-low hover:bg-conf-low/10"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col text-sm">
      <span className="mb-1 text-gray-600">{label}</span>
      {children}
    </label>
  );
}

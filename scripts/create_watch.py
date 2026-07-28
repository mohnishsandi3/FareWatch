"""Create a user + watch from the CLI — for end-to-end testing of Phase 3.

(Full auth + a watch-management UI belong to the API/web layer in Phase 4; this
is just enough to exercise the matcher/notifier pipeline.)

Examples:
  # Anywhere from Boston under $400 over the next 3 months:
  python -m scripts.create_watch --email you@example.com --origin BOS \
      --max-price 400 --start 2026-06-01 --end 2026-09-01

  # Fixed route BOS->LON, any price:
  python -m scripts.create_watch --email you@example.com --origin BOS \
      --destination LON --start 2026-06-01 --end 2026-09-01
"""
from __future__ import annotations

import argparse
from datetime import date

from shared import db


def main() -> None:
    p = argparse.ArgumentParser(description="Create a user + watch")
    p.add_argument("--email", required=True)
    p.add_argument("--origin", required=True, help="IATA city code, e.g. BOS")
    p.add_argument("--destination", default=None, help="IATA code, or omit for anywhere/flexible")
    p.add_argument("--max-price", type=float, default=None)
    p.add_argument("--start", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    p.add_argument("--cabin", default="economy")
    p.add_argument("--fixed-dates", action="store_true", help="not flexible on dates")
    args = p.parse_args()

    with db.get_conn() as conn:
        user_id = db.create_user(conn, args.email)
        watch_id = db.create_watch(
            conn,
            user_id=user_id,
            origin=args.origin,
            destination=args.destination,
            max_price=args.max_price,
            date_window_start=args.start,
            date_window_end=args.end,
            flexible_dates=not args.fixed_dates,
            cabin=args.cabin,
        )
        conn.commit()

    dest = args.destination or "anywhere"
    print(f"user {user_id}\nwatch {watch_id}: {args.origin}->{dest} "
          f"max={args.max_price} {args.start}..{args.end}")


if __name__ == "__main__":
    main()

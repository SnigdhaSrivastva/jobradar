"""jobradar command line: fetch → score → store, then report, tailor and track."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import truststore
import yaml

from jobradar.profile import load_fact_bank, load_profile
from jobradar.report import render
from jobradar.scoring import score
from jobradar.sources import Board, Job, fetch_all
from jobradar.store import STATUSES, Store
from jobradar.tailor import tailor, verify_grounded


def load_boards(path: str | Path) -> list[Board]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [Board(platform=b["platform"], slug=b["slug"], company=b.get("company", b["slug"])) for b in data["boards"]]


def _job_from_row(row: object) -> Job:
    r = dict(row)  # type: ignore[call-overload]
    return Job(platform=r["platform"], company=r["company"], job_id=r["key"].split(":", 2)[2], title=r["title"],
               location=r["location"], remote=bool(r["remote"]), url=r["url"], description=r["description"],
               posted_at=None, salary=r["salary"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jobradar", description=__doc__)
    p.add_argument("--db", default="jobradar.sqlite")
    p.add_argument("--profile", default="example/profile.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="fetch boards, score and store")
    f.add_argument("--boards", default="example/boards.yaml")

    r = sub.add_parser("report", help="write the static HTML dashboard")
    r.add_argument("--out", default="site/index.html")
    r.add_argument("--min-score", type=float, default=0)

    sub.add_parser("top", help="print the best current matches").add_argument("-n", type=int, default=15)

    t = sub.add_parser("tailor", help="pick verified resume bullets for a job")
    t.add_argument("key")
    t.add_argument("--facts", default="example/factbank.yaml")

    s = sub.add_parser("status", help="track an application")
    s.add_argument("key")
    s.add_argument("status", choices=STATUSES)

    args = p.parse_args(argv)
    # Use the OS certificate store so fetching works behind corporate TLS inspection.
    truststore.inject_into_ssl()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    store = Store(args.db)
    try:
        if args.cmd == "fetch":
            profile = load_profile(args.profile)
            boards = load_boards(args.boards)
            result = fetch_all(boards)
            scored = [(job, score(job, profile)) for job in result.jobs]
            fetched = {b.company for b in boards if f"{b.platform}:{b.slug}" not in result.errors}
            summary = store.upsert(scored, fetched)
            print(f"{len(result.jobs)} postings from {len(fetched)}/{len(boards)} boards: "
                  f"{summary['new']} new, {summary['updated']} updated, {summary['closed']} closed")
            for board, error in result.errors.items():
                print(f"  ! {board}: {error}")
        elif args.cmd == "report":
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render(store.top(args.min_score, limit=500), store.counts()), encoding="utf-8")
            print(f"wrote {out}")
        elif args.cmd == "top":
            for row in store.top(limit=args.n):
                print(f"{row['score']:5.1f}  {row['company']:<14} {row['title'][:60]:<60} {row['key']}")
        elif args.cmd == "tailor":
            found = store.get(args.key)
            if found is None:
                print(f"unknown job {args.key}", file=sys.stderr)
                return 2
            bank = load_fact_bank(args.facts)
            resume = tailor(_job_from_row(found), load_profile(args.profile), bank)
            assert verify_grounded(resume, bank)
            print(f"{found['title']} @ {found['company']}\n")
            for fact in resume.bullets:
                print(f"- {fact.text}")
            print(f"\nemphasized: {', '.join(resume.emphasized_skills) or '-'}")
            print(f"not evidenced by any bullet: {', '.join(resume.uncovered_skills) or '-'}")
        elif args.cmd == "status":
            store.set_status(args.key, args.status)
            print(f"{args.key} → {args.status}")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())

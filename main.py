#!/usr/bin/env python3
import sys
import os
import csv
import re
import argparse
import subprocess
from datetime import date
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

console = Console()

OUTREACH_AGENT_PATH = "/Users/nishit/Desktop/outreach-agent/main.py"


def save_leads_csv(leads, niche: str) -> str:
    """Append leads to a CSV file named after the niche and date. Returns file path."""
    safe_niche = re.sub(r"[^\w\s-]", "", niche).strip().replace(" ", "_")[:40]
    filename = f"leads_{safe_niche}_{date.today()}.csv"
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)

    file_exists = os.path.exists(filepath)
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "company_name", "score", "source", "description",
            "website", "email", "linkedin", "why_good_lead", "url",
        ])
        if not file_exists:
            writer.writeheader()
        for lead in leads:
            writer.writerow({
                "company_name": lead.company_name,
                "score": lead.score,
                "source": lead.source,
                "description": lead.description,
                "website": lead.website or lead.url,
                "email": lead.email,
                "linkedin": lead.linkedin,
                "why_good_lead": lead.why_good_lead,
                "url": lead.url,
            })
    return filepath


def generate_leads(niche: str) -> tuple[list, str]:
    """Run lead generation and save CSV. Returns (leads, filepath)."""
    from agent import find_leads
    from display import display_leads

    console.print(f"\n[bold]Searching for B2B leads:[/bold] {niche}")
    console.print("[dim]Orchestrating searches across multiple sources...[/dim]\n")

    leads = find_leads(niche, verbose=True)
    display_leads(leads, niche)

    filepath = ""
    if leads:
        filepath = save_leads_csv(leads, niche)
        console.print(f"[bold green]Saved {len(leads)} leads →[/bold green] [cyan]{filepath}[/cyan]\n")

    return leads, filepath


def run_filter(csv_path: str, min_score: int | None = None, has_email: bool = False,
               has_website: bool = False, business_type: str | None = None,
               location: str | None = None, outreach: bool = False) -> str | None:
    """Load CSV, filter, display, save. Returns filtered CSV path or None."""
    from filter import load_leads_csv, filter_leads, save_filtered_csv
    from filter_display import display_filtered_leads

    if not os.path.exists(csv_path):
        console.print(f"[red]File not found:[/red] {csv_path}")
        return None

    leads = load_leads_csv(csv_path)
    if not leads:
        console.print("[red]No leads found in CSV.[/red]")
        return None

    filtered = filter_leads(
        leads,
        min_score=min_score,
        has_email=has_email,
        has_website=has_website,
        business_type=business_type,
        location=location,
    )

    display_filtered_leads(filtered, len(leads))

    if not filtered:
        return None

    filtered_path = save_filtered_csv(filtered, csv_path)
    console.print(f"[bold green]Saved {len(filtered)} filtered leads →[/bold green] [cyan]{filtered_path}[/cyan]\n")

    if outreach:
        launch_outreach(filtered_path)

    return filtered_path


def launch_outreach(csv_path: str):
    """Launch outreach-agent with the given CSV."""
    if not os.path.exists(OUTREACH_AGENT_PATH):
        console.print(f"[yellow]Outreach agent not found at {OUTREACH_AGENT_PATH}[/yellow]")
        return
    console.print(f"[bold]Launching outreach agent...[/bold]")
    subprocess.run([sys.executable, OUTREACH_AGENT_PATH, csv_path])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="leads-agent",
        description="B2B Lead Finder with filtering and outreach pipeline",
    )
    subparsers = parser.add_subparsers(dest="command")

    # filter subcommand
    filt = subparsers.add_parser("filter", help="Filter and prioritize leads from a CSV")
    filt.add_argument("csv_path", help="Path to leads CSV file")
    filt.add_argument("--score", type=int, default=None, help="Minimum lead score (1-10)")
    filt.add_argument("--has-email", action="store_true", help="Only leads with email")
    filt.add_argument("--has-website", action="store_true", help="Only leads with website")
    filt.add_argument("--type", dest="business_type", choices=["saas", "agency", "local_service", "ecommerce", "other"],
                       help="Filter by business type")
    filt.add_argument("--location", type=str, default=None, help="Filter by location")
    filt.add_argument("--outreach", action="store_true", help="Auto-launch outreach agent after filtering")

    # pipeline subcommand
    pipe = subparsers.add_parser("pipeline", help="Generate leads + filter + optionally launch outreach")
    pipe.add_argument("niche", help="Niche to search for leads")
    pipe.add_argument("--score", type=int, default=None, help="Minimum lead score (1-10)")
    pipe.add_argument("--has-email", action="store_true", help="Only leads with email")
    pipe.add_argument("--has-website", action="store_true", help="Only leads with website")
    pipe.add_argument("--type", dest="business_type", choices=["saas", "agency", "local_service", "ecommerce", "other"],
                       help="Filter by business type")
    pipe.add_argument("--location", type=str, default=None, help="Filter by location")
    pipe.add_argument("--outreach", action="store_true", help="Auto-launch outreach agent after filtering")

    return parser


def main():
    # Backward compatibility: if first arg is not a subcommand, treat as niche
    if len(sys.argv) > 1 and sys.argv[1] not in ("filter", "pipeline", "-h", "--help"):
        niche = " ".join(sys.argv[1:])
        generate_leads(niche)
        return

    if len(sys.argv) == 1:
        # Interactive mode
        console.print("\n[bold]B2B Lead Finder[/bold]\n")
        niche = console.input("[bold cyan]Enter niche to search:[/bold cyan] ").strip()
        if not niche:
            console.print("[red]No niche provided. Exiting.[/red]")
            sys.exit(1)
        generate_leads(niche)
        return

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "filter":
        run_filter(
            csv_path=args.csv_path,
            min_score=args.score,
            has_email=args.has_email,
            has_website=args.has_website,
            business_type=args.business_type,
            location=args.location,
            outreach=args.outreach,
        )

    elif args.command == "pipeline":
        # Step 1: Generate
        leads, csv_path = generate_leads(args.niche)
        if not csv_path:
            console.print("[red]No leads generated. Pipeline stopped.[/red]")
            return

        # Step 2: Filter & prioritize
        console.print("[bold]── Filtering & Prioritizing ──[/bold]\n")
        run_filter(
            csv_path=csv_path,
            min_score=args.score,
            has_email=args.has_email,
            has_website=args.has_website,
            business_type=args.business_type,
            location=args.location,
            outreach=args.outreach,
        )


if __name__ == "__main__":
    main()

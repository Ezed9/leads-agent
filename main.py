#!/usr/bin/env python3
import sys
import os
import csv
import re
from datetime import date
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

console = Console()


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


def main():
    if len(sys.argv) > 1:
        niche = " ".join(sys.argv[1:])
    else:
        console.print("\n[bold]B2B Lead Finder[/bold]\n")
        niche = console.input("[bold cyan]Enter niche to search:[/bold cyan] ").strip()
        if not niche:
            console.print("[red]No niche provided. Exiting.[/red]")
            sys.exit(1)

    from agent import find_leads
    from display import display_leads

    console.print(f"\n[bold]Searching for B2B leads:[/bold] {niche}")
    console.print("[dim]Orchestrating searches across multiple sources...[/dim]\n")

    leads = find_leads(niche, verbose=True)
    display_leads(leads, niche)

    if leads:
        filepath = save_leads_csv(leads, niche)
        console.print(f"[bold green]Saved {len(leads)} leads →[/bold green] [cyan]{filepath}[/cyan]\n")


if __name__ == "__main__":
    main()

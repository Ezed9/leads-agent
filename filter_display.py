"""Rich CLI display for filtered leads."""

from rich.console import Console
from rich.table import Table
from rich.text import Text
from models import FilteredLead

console = Console()


def _shorten(s: str, n: int = 35) -> str:
    return s[:n] + "…" if len(s) > n else s


def priority_color(score: float) -> str:
    if score >= 70:
        return "bold green"
    elif score >= 40:
        return "yellow"
    return "red"


def display_filtered_leads(leads: list[FilteredLead], original_count: int) -> None:
    if not leads:
        console.print("\n[bold red]No leads matched the filters.[/bold red]\n")
        return

    table = Table(
        title="[bold]Filtered & Prioritized Leads[/bold]",
        show_lines=True,
        expand=True,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Company", style="bold", min_width=16)
    table.add_column("Type", width=14, justify="center")
    table.add_column("Location", width=14)
    table.add_column("Score", width=6, justify="center")
    table.add_column("Priority", width=8, justify="center")
    table.add_column("Email", min_width=16)
    table.add_column("LinkedIn", min_width=18)
    table.add_column("Website", min_width=18)
    table.add_column("URL", min_width=18)
    table.add_column("Why Good Lead", min_width=24)

    for i, lead in enumerate(leads, 1):
        score_style = "bold green" if lead.score >= 7 else ("yellow" if lead.score >= 4 else "red")
        score_text = Text(str(lead.score), style=score_style)
        priority_text = Text(str(lead.priority_score), style=priority_color(lead.priority_score))
        type_text = Text(lead.business_type, style="cyan")

        table.add_row(
            str(i),
            lead.company_name,
            type_text,
            lead.location or "-",
            score_text,
            priority_text,
            _shorten(lead.email, 28) if lead.email else "-",
            _shorten(lead.linkedin, 30) if lead.linkedin else "-",
            _shorten(lead.website or "", 30) if lead.website else "-",
            _shorten(lead.url, 30) if lead.url else "-",
            lead.why_good_lead[:160] + ("…" if len(lead.why_good_lead) > 160 else ""),
        )

    console.print()
    console.print(table)

    top = leads[0]
    console.print(
        f"\n[dim]Filtered {original_count} → {len(leads)} leads[/dim] | "
        f"[bold]Top priority:[/bold] {top.company_name} ({top.priority_score})\n"
    )

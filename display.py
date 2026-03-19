from rich.console import Console
from rich.table import Table
from rich.text import Text
from models import Lead

console = Console()


def _shorten(s: str, n: int = 35) -> str:
    return s[:n] + "…" if len(s) > n else s


def score_color(score: int) -> str:
    if score >= 7:
        return "bold green"
    elif score >= 4:
        return "yellow"
    return "red"


def source_style(source: str) -> str:
    return {
        "github": "bold cyan",
        "reddit": "bold magenta",
        "google": "bold blue",
        "producthunt": "bold orange1",
        "maps": "bold green",
    }.get(source, "white")


def display_leads(leads: list[Lead], niche: str) -> None:
    if not leads:
        console.print(
            "\n[bold red]No leads found.[/bold red] "
            "Try a different niche or check your API keys.\n"
        )
        return

    table = Table(
        title=f"[bold]B2B Leads: {niche}[/bold]",
        show_lines=True,
        expand=True,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Company", style="bold", min_width=16)
    table.add_column("Source", width=10, justify="center")
    table.add_column("Description", min_width=22)
    table.add_column("Website", min_width=20)
    table.add_column("Email", min_width=18)
    table.add_column("LinkedIn", min_width=18)
    table.add_column("Why Good Lead", min_width=28)
    table.add_column("Score", width=6, justify="center")

    for i, lead in enumerate(leads, 1):
        score_text = Text(str(lead.score), style=score_color(lead.score))
        source_text = Text(lead.source.upper(), style=source_style(lead.source))

        website = lead.website or lead.url
        email = lead.email or ""
        linkedin = lead.linkedin or ""

        table.add_row(
            str(i),
            lead.company_name,
            source_text,
            lead.description[:140] + ("…" if len(lead.description) > 140 else ""),
            _shorten(website),
            _shorten(email, 30),
            _shorten(linkedin),
            lead.why_good_lead[:180] + ("…" if len(lead.why_good_lead) > 180 else ""),
            score_text,
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]Total leads found: {len(leads)}[/dim]\n")

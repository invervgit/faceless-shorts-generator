import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from shorts.pipeline import JobSpec, generate
from shorts.sources import registry
from shorts.tts import list_voices

app = typer.Typer(help="Faceless Shorts Generator CLI")
console = Console()

def run_async(coro):
    return asyncio.run(coro)

@app.command(name="generate")
def generate_short(
    topic: str = typer.Argument(..., help="The topic for the short video"),
    tone: str = typer.Option("documentary", help="Tone of the script (documentary, motivational, etc)"),
    duration: int = typer.Option(30, help="Target duration in seconds"),
    voice: str = typer.Option("en-US-ChristopherNeural", help="TTS Voice ID"),
    style: str = typer.Option("karaoke", help="Caption style"),
    keep_temp: bool = typer.Option(False, "--keep-temp", help="Keep temporary working directories"),
):
    """Generate a single short video from a topic."""
    job = JobSpec(
        topic=topic,
        tone=tone,
        duration=duration,
        voice_id=voice,
        style=style,
        keep_temp=keep_temp
    )
    
    async def _run():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task(f"Generating: {topic}", total=100)
            
            async for event in generate(job):
                progress.update(task, completed=event.pct, description=event.message)
                if event.error:
                    console.print(f"\n[red]Error: {event.error}[/red]")
                    sys.exit(1)
                if event.is_done and not event.error:
                    console.print(f"\n[green]Success! Video saved to {event.result_path}[/green]")
                    
    run_async(_run())

@app.command(name="batch")
def batch_generate(
    topics_file: Path = typer.Argument(..., help="Text file with one topic per line"),
    parallel: int = typer.Option(1, help="Number of concurrent jobs"),
    tone: str = typer.Option("documentary"),
):
    """Generate multiple shorts from a text file."""
    if not topics_file.exists():
        console.print("[red]Topics file not found.[/red]")
        sys.exit(1)
        
    topics = [line.strip() for line in topics_file.read_text().splitlines() if line.strip()]
    console.print(f"Loaded {len(topics)} topics.")
    
    async def _run_batch():
        sem = asyncio.Semaphore(parallel)
        
        async def _worker(topic):
            async with sem:
                console.print(f"Starting: {topic}")
                job = JobSpec(topic=topic, tone=tone)
                last_event = None
                async for event in generate(job):
                    last_event = event
                if last_event and last_event.result_path:
                    console.print(f"[green]Finished: {topic} -> {last_event.result_path}[/green]")
                else:
                    console.print(f"[red]Failed: {topic}[/red]")
                    
        await asyncio.gather(*[_worker(t) for t in topics])
        
    run_async(_run_batch())

@app.command(name="voices")
def voices_list(lang: str = typer.Option("en", help="Language code filter")):
    """List available TTS voices."""
    async def _run():
        v = await list_voices()
        for group, items in v.items():
            if lang.lower() in group.lower():
                console.print(f"\n[bold blue]{group}[/bold blue]")
                for item in items:
                    console.print(f"  - {item['voice_id']} ({item['friendly_name']})")
    run_async(_run())

@app.command(name="sources")
def sources_health(health: bool = typer.Option(False, "--health", help="Check circuit breaker health")):
    """Manage image sources and health."""
    if health:
        console.print("[bold]Circuit Breaker Health:[/bold]")
        cur = registry.breaker.conn.execute("SELECT source, consecutive_failures, latency, skip_until FROM source_health")
        import time
        for row in cur.fetchall():
            status = "OPEN (Blocked)" if row[3] > time.time() else "CLOSED (Healthy)"
            color = "red" if "OPEN" in status else "green"
            console.print(f"Source: {row[0]}, Fails: {row[1]}, Latency: {row[2]:.2f}s, Status: [{color}]{status}[/{color}]")

@app.command(name="cache")
def cache_cmd(
    clear: bool = typer.Option(False, "--clear", help="Clear cache"),
    older_than: str = typer.Option("30d", help="Clear cache older than (e.g. 30d)")
):
    """Manage the local disk cache."""
    from shorts.cache import cache
    if clear:
        import shutil
        shutil.rmtree(cache.cache_dir, ignore_errors=True)
        cache.cache_dir.mkdir(parents=True, exist_ok=True)
        console.print("[green]Cache completely cleared.[/green]")
    else:
        size = sum(f.stat().st_size for f in cache.cache_dir.glob('**/*') if f.is_file())
        console.print(f"Total cache size: {size / (1024*1024):.2f} MB")

@app.command(name="keys")
def setup_keys(setup: bool = typer.Option(False, "--setup", help="Interactive key setup wizard")):
    """Manage API keys."""
    if not setup:
        console.print("Run `shorts keys --setup` to configure API keys interactively.")
        return
        
    from dotenv import set_key
    env_path = ".env"
    Path(env_path).touch(exist_ok=True)
    
    keys_map = {
        "GROQ_API_KEY": "Groq (llama-3.3-70b-versatile)",
        "CEREBRAS_API_KEY": "Cerebras (llama-3.3-70b)",
        "GEMINI_API_KEY": "Google Gemini (gemini-2.0-flash)",
        "PEXELS_API_KEY": "Pexels (Stock Photos/Video)",
        "PIXABAY_API_KEY": "Pixabay (Stock Media)",
        "UNSPLASH_ACCESS_KEY": "Unsplash (Photos)"
    }
    
    console.print("[bold]Interactive Key Setup Wizard[/bold]\nLeave blank to skip.\n")
    for var, desc in keys_map.items():
        current = os.getenv(var)
        val = typer.prompt(f"{desc} [{var}]", default="***" if current else "", show_default=True)
        if val and val != "***":
            set_key(env_path, var, val)
            os.environ[var] = val
    console.print("\n[green]Setup complete! .env updated.[/green]")

@app.command(name="doctor")
def run_doctor():
    """Check system health, dependencies, and connections."""
    import shutil
    import subprocess
    import httpx
    
    console.print("[bold]Shorts Doctor[/bold]\n")
    
    # FFmpeg
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        res = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        version = res.stdout.split("\n")[0]
        console.print(f"[green]✓ FFmpeg found:[/green] {version}")
    else:
        console.print("[red]✗ FFmpeg not found[/red] - Please install it.")
        
    # Fonts
    font_path = Path("assets/fonts/Montserrat-ExtraBold.ttf")
    if font_path.exists():
        console.print(f"[green]✓ Fonts registered:[/green] {font_path}")
    else:
        console.print(f"[red]✗ Font missing:[/red] {font_path}")
        
    # Disk Space
    total, used, free = shutil.disk_usage(".")
    console.print(f"[green]✓ Disk Space:[/green] {free // (1024**3)}GB free")
    
    # Endpoints
    endpoints = {
        "Wikimedia API": "https://en.wikipedia.org/w/api.php",
        "Edge-TTS Endpoint": "https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1"
    }
    
    with httpx.Client(timeout=5) as client:
        for name, url in endpoints.items():
            try:
                client.get(url)
                console.print(f"[green]✓ Reachable:[/green] {name}")
            except Exception:
                console.print(f"[red]✗ Unreachable:[/red] {name}")

def main():
    app()
    
if __name__ == "__main__":
    main()

import time
import shutil
import logging
from pathlib import Path
from typing import Optional

import base64
import sys
from io import BytesIO

try:
    from PIL import Image
except ImportError:
    Image = None

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.align import Align
from rich.text import Text
from rich.panel import Panel

_LOG = logging.getLogger("kaiagotchi.ui.splash")

class SplashScreen:
    def __init__(self, image_path: str = "images/kaia.png"):
        self.console = Console()
        # Resolve absolute path relative to project root if possible
        # Assuming this runs from project root or we find it relative to this file
        self.image_path = Path(image_path)
        if not self.image_path.exists():
            # Try finding it relative to the package
            root = Path(__file__).parent.parent.parent
            self.image_path = root / image_path
        
        self.ascii_art = self._load_image_as_ascii()

    def _load_image_as_ascii(self, width: int = 60) -> str:
        """Convert image to ASCII art using Pillow."""
        if not Image or not self.image_path.exists():
            return self._fallback_ascii()

        try:
            img = Image.open(self.image_path)
            
            # Resize maintaining aspect ratio (font aspect ratio is roughly 2:1)
            w_percent = (width / float(img.size[0]))
            h_size = int((float(img.size[1]) * float(w_percent)) * 0.5)
            img = img.resize((width, h_size), Image.Resampling.LANCZOS)
            img = img.convert('L')  # Grayscale

            pixels = img.getdata()
            chars = ["@", "#", "S", "%", "?", "*", "+", ";", ":", ",", "."]
            new_pixels = [chars[pixel // 25] for pixel in pixels]
            new_pixels = ''.join(new_pixels)

            ascii_image = [new_pixels[index:index + width] for index in range(0, len(new_pixels), width)]
            return "\n".join(ascii_image)
        except Exception as e:
            _LOG.error(f"Failed to load splash image: {e}")
            return self._fallback_ascii()

    def _fallback_ascii(self) -> str:
        return """
   __ __      _                  _       _     _ 
  / //_/____ (_)___ _____ _____ | |_ ___| |__ (_)
 / ,<  / __ `/ / __ `/ __ `/ __ | __/ __| '_ \| |
/ /| |/ /_/ / / /_/ / /_/ / /_/ | || (__| | | | |
/_/ |_|\__,_/_/\__,_/\__, /\____|\__\___|_| |_|_|
                    /____/                       
        """

    def _render_kitty_image(self) -> bool:
        """
        Render image using Kitty Graphics Protocol.
        Returns True if successful, False otherwise.
        """
        if not Image or not self.image_path.exists():
            return False

        try:
            # Check if we are likely in a Kitty terminal
            # This is a heuristic; reliable detection is harder without query/response
            # But the user explicitly asked for this.
            
            # Load image fresh
            img = Image.open(self.image_path)

            # Resize image to a reasonable size for the splash (e.g., 400px width)
            # This ensures it fits and allows us to estimate centering
            target_width = 400
            w_percent = (target_width / float(img.size[0]))
            h_size = int((float(img.size[1]) * float(w_percent)))
            img = img.resize((target_width, h_size), Image.Resampling.LANCZOS)

            # Save to bytes for encoding
            with BytesIO() as output:
                img.save(output, format="PNG")
                img_data = output.getvalue()
                
            encoded = base64.standard_b64encode(img_data)
            
            # Chunking logic for Kitty protocol
            # Chunks must be <= 4096 bytes
            chunk_size = 4096
            
            # Calculate centering
            # Assume roughly 10px per column (common for terminals)
            # This is an estimation but better than hard left
            est_cols = target_width // 9 
            term_cols = shutil.get_terminal_size().columns
            start_col = max(1, (term_cols - est_cols) // 2)
            
            # Clear screen first
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
            
            # Move cursor down a bit to center vertically (approx)
            sys.stdout.write("\n" * 2)
            
            # Move cursor to center horizontally
            sys.stdout.write(f"\033[{start_col}G")
            
            # We need to split the base64 data
            total_len = len(encoded)
            
            chunks = [encoded[i:i+chunk_size] for i in range(0, total_len, chunk_size)]
            
            for i, chunk in enumerate(chunks):
                m = 1 if i < len(chunks) - 1 else 0
                payload = chunk.decode('ascii')
                
                # First chunk header
                if i == 0:
                    # a=T: transmit and display
                    # f=100: PNG
                    # m=1: more chunks coming (or 0 if last)
                    cmd = f"\033_Gf=100,a=T,m={m};{payload}\033\\"
                else:
                    # Continuation chunk
                    cmd = f"\033_Gm={m};{payload}\033\\"
                
                sys.stdout.write(cmd)
                
            sys.stdout.write("\n") # Newline after image
            sys.stdout.flush()
            return True
            
        except Exception as e:
            _LOG.error(f"Failed to render Kitty image: {e}")
            return False

    async def show(self, duration: float = 15.0):
        """Display splash screen with progress bar."""
        self.console.clear()
        
        # Try Kitty graphics first
        if not self._render_kitty_image():
            # Fallback to ASCII
            styled_art = Text(self.ascii_art, style="bold cyan")
            self.console.print("\n" * 2)
            self.console.print(Align.center(styled_art))
            self.console.print("\n")
        else:
            # If Kitty image rendered, we just need some padding for the bar
            self.console.print("\n")

        # Progress bar
        # We can't use the context manager easily with async sleep inside, 
        # but Rich Progress works fine if we manually start/stop or just use it as is.
        # Actually, we can use it as a context manager, just await sleep inside.
        
        import asyncio
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40, style="cyan", complete_style="bold cyan"),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Initializing Kaiagotchi systems...", total=100)
            
            steps = 100
            step_delay = duration / steps
            
            for i in range(steps):
                await asyncio.sleep(step_delay)
                progress.update(task, advance=1)
                
                # Simulate loading stages
                if i == 10:
                    progress.update(task, description="[green]Loading neural pathways...")
                elif i == 30:
                    progress.update(task, description="[green]Connecting to hardware interfaces...")
                elif i == 60:
                    progress.update(task, description="[green]Calibrating emotional sensors...")
                elif i == 85:
                    progress.update(task, description="[green]Establishing neural link...")
        
        self.console.clear()

import logging
import sys
from typing import Optional

def setup_logging(debug: bool = False, 
                 log_file: Optional[str] = None) -> None:
    """Configure application logging."""
    
    level = logging.DEBUG if debug else logging.INFO
    format_str = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
        
    logging.basicConfig(
        level=level,
        format=format_str,
        handlers=handlers
    )
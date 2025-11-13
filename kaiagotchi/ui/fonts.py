"""
Fonts module for terminal version - provides placeholder fonts.
"""

class Font:
    """Placeholder font class for terminal version."""
    def __init__(self, name, size):
        self.name = name
        self.size = size
    
    def getsize(self, text):
        """Get the size of text in this font (placeholder)."""
        return (len(text) * 6, 12)  # Rough estimate for terminal

# Create some basic font placeholders
Small = Font("Terminal", 8)
Medium = Font("Terminal", 12) 
Large = Font("Terminal", 16)

# Font constants for compatibility
FONT_NAMES = {
    'small': Small,
    'medium': Medium, 
    'large': Large
}

def load_font(name, size):
    """Load a font by name and size."""
    return Font(name, size)

def init(config):
    """
    Initialize fonts from configuration.
    For terminal version, this is a no-op.
    """
    # Terminal version doesn't need font initialization
    pass

def get_font(name):
    """Get a font by name."""
    return FONT_NAMES.get(name, Medium)
# Compatibility class for plugins
class Fonts:
    """Compatibility class for plugins expecting Fonts as a class."""
    
    Small = Small
    Medium = Medium 
    Large = Large
    
    @staticmethod
    def load_font(name, size):
        return load_font(name, size)
    
    @staticmethod  
    def get_font(name):
        return get_font(name)
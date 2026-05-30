"""
UI Components for plugins compatibility
"""
from kaiagotchi.ui.view import View
from kaiagotchi.ui.display import Display
from kaiagotchi.ui.faces import Faces
from kaiagotchi.ui.fonts import Fonts
# Color constants for plugin compatibility
BLACK = 0
WHITE = 1

# Placeholder UI component classes for plugin compatibility
class LabeledValue:
    """Placeholder for LabeledValue UI component."""
    def __init__(self, label, value, color=None, position=None):
        self.label = label
        self.value = value
        self.color = color
        self.position = position

class Text:
    """Placeholder for Text UI component."""
    def __init__(self, value, color=None, position=None, font=None):
        self.value = value
        self.color = color
        self.position = position
        self.font = font

# Re-export commonly used components for plugin compatibility
__all__ = ['View', 'Display', 'Faces', 'Fonts', 'LabeledValue', 'Text']
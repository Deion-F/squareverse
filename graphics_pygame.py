import pygame
from typing import Tuple, Dict, Optional, Union, List
import threading

class Point:
    """Compatibility wrapper for Point coordinates."""
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

class Line:
    """Compatibility wrapper for Line objects."""
    def __init__(self, p1: Point, p2: Point):
        self.p1 = p1
        self.p2 = p2
        self._color = (0, 0, 0)  # Default black
        
    def setOutline(self, color):
        """Set line color."""
        if isinstance(color, str):
            self._color = GraphWin.color_name_to_rgb(color)
        else:
            self._color = color
            
    def setFill(self, color):
        """Alias for setOutline for compatibility."""
        self.setOutline(color)
            
    def draw(self, window):
        """Draw line to window and store reference."""
        pygame.draw.line(
            window.screen,
            self._color,
            (int(self.p1.x), int(self.p1.y)),
            (int(self.p2.x), int(self.p2.y))
        )
        # Add line to window's shape tracking
        window.items.append(self)
        return self

class Rectangle:
    """Compatibility wrapper for Rectangle objects with efficient batch operations."""
    def __init__(self, p1: Point, p2: Point):
        self.p1 = p1
        self.p2 = p2
        self._fill_color = (255, 255, 255)  # Default white
        self._outline_color = (0, 0, 0)      # Default black
        self._outline_width = 1
        self._rect = pygame.Rect(
            min(p1.x, p2.x),
            min(p1.y, p2.y),
            abs(p2.x - p1.x),
            abs(p2.y - p1.y)
        )
        self._dirty = True  # Track if needs redraw
        self.tkinter_id = None  # Compatibility with original code
        
    @property
    def rect(self) -> pygame.Rect:
        """Get pygame Rect for efficient collision detection."""
        return self._rect
        
    def move(self, dx: float, dy: float):
        """Move rectangle by delta x and y."""
        self.p1.x += dx
        self.p1.y += dy
        self.p2.x += dx
        self.p2.y += dy
        self._rect.move_ip(dx, dy)
        
    def getCoordinates(self) -> str:
        """Get coordinates in the original format."""
        return f"{self.p1.x}:{self.p1.y}:{self.p2.x}:{self.p2.y}"
        
    def clone(self) -> 'Rectangle':
        """Create a copy of this rectangle."""
        new_rect = Rectangle(
            Point(self.p1.x, self.p1.y),
            Point(self.p2.x, self.p2.y)
        )
        new_rect._fill_color = self._fill_color
        new_rect._outline_color = self._outline_color
        new_rect._outline_width = self._outline_width
        return new_rect
        
    def setWidth(self, width: int):
        """Set outline width."""
        self._outline_width = width
        
    def draw_square(self, window, square) -> int:
        """Draw square and return ID."""
        self.tkinter_id = id(square)  # Use object id as unique identifier
        window.add_shape(self)
        return self.tkinter_id

    def setFill(self, color):
        """Set fill color - accepts either pygame color tuple or color name."""
        if isinstance(color, str):
            self._fill_color = GraphWin.color_name_to_rgb(color)
        else:
            # Ensure valid RGB values (0-255)
            r, g, b = color
            self._fill_color = (
                max(0, min(255, int(r))),
                max(0, min(255, int(g))),
                max(0, min(255, int(b)))
            )

    def setOutline(self, color):
        """Set outline color."""
        if isinstance(color, str):
            self._outline_color = GraphWin.color_name_to_rgb(color)
        else:
            # Ensure valid RGB values (0-255)
            r, g, b = color
            self._outline_color = (
                max(0, min(255, int(r))),
                max(0, min(255, int(g))),
                max(0, min(255, int(b)))
            )

    def draw(self, window):
        """Draw rectangle to window and store reference."""
        if isinstance(window, GraphWin):
            self.tkinter_id = id(self)  # Generate unique ID
            window.add_shape(self)
            return self

class GraphWin:
    """Pygame-based window implementation maintaining graphics.py compatibility."""
    
    def __init__(self, title: str, width: int, height: int, autoflush: bool = True):
        """Initialize pygame window with same parameters as graphics.py."""
        pygame.init()
        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(title)
        self.background_color = (255, 255, 255)  # Default white
        self.clock = pygame.time.Clock()
        self.running = True
        self.autoflush = autoflush
        self.shapes: Dict[int, Rectangle] = {}  # Store shapes by ID
        self.items = []  # Compatibility with original code
        self.squares = []  # Compatibility with original code
        
        # Mouse state
        self.last_click = None
        self.mouse_clicked = False
        
        # Event handling
        self._handle_events()

    def _handle_events(self):
        """Handle pygame events."""
        pygame.event.pump()  # Process OS events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self.last_click = Point(*pygame.mouse.get_pos())
                self.mouse_clicked = True
        self.clock.tick(60)  # Limit to 60 FPS

    def setBackground(self, color):
        """Set background color."""
        if isinstance(color, str):
            self.background_color = self.color_name_to_rgb(color)
        else:
            self.background_color = color
        self.screen.fill(self.background_color)
        if self.autoflush:
            pygame.display.flip()

    def checkMouse(self) -> Optional[Point]:
        """Check for mouse clicks and handle events."""
        self._handle_events()  # Process events
        
        if self.mouse_clicked:
            self.mouse_clicked = False
            click = self.last_click
            self.last_click = None
            return click
        return None

    def add_shape(self, shape: Rectangle):
        """Add shape to tracking dictionary."""
        if shape.tkinter_id is not None:
            self.shapes[shape.tkinter_id] = shape
            if shape not in self.items:
                self.items.append(shape)
                
    def batch_update_squares(self, updates: List[Dict]):
        """Batch update multiple squares at once."""
        for update in updates:
            if 'tkinter_id' in update:
                shape = self.shapes.get(update['tkinter_id'])
                if shape:
                    shape._rect.x = update['p1']['x']
                    shape._rect.y = update['p1']['y']
                    if 'outline_color' in update:
                        shape._outline_color = update['outline_color']
        self.update()

    def move_by_id(self, tkinter_id: int, dx: float, dy: float):
        """Move shape by ID."""
        if tkinter_id in self.shapes:
            shape = self.shapes[tkinter_id]
            shape.p1.x += dx
            shape.p1.y += dy
            shape.p2.x += dx
            shape.p2.y += dy
            shape._rect.move_ip(dx, dy)
            if self.autoflush:
                self.update()

    def update(self):
        """Update display with all current shapes and lines."""
        self._handle_events()  # Process events each frame
        
        # Clear screen
        self.screen.fill(self.background_color)
        
        # Draw all items in order (lines and other non-rectangle shapes)
        for item in self.items:
            if isinstance(item, Line):
                pygame.draw.line(
                    self.screen,
                    item._color,
                    (int(item.p1.x), int(item.p1.y)),
                    (int(item.p2.x), int(item.p2.y))
                )
        
        # Draw all tracked shapes (rectangles)
        for shape in self.shapes.values():
            # Draw fill
            pygame.draw.rect(self.screen, shape._fill_color, shape._rect)
            # Draw outline if different from fill
            if shape._outline_color != shape._fill_color:
                pygame.draw.rect(self.screen, shape._outline_color, shape._rect, 1)
                
        # Update display
        pygame.display.flip()

    def close(self):
        """Close the window and clean up pygame."""
        self.running = False
        try:
            pygame.display.quit()
            pygame.quit()
        except pygame.error:
            pass  # Window might already be closed

    def delItem(self, item):
        """Remove item from tracking."""
        if item.tkinter_id in self.shapes:
            del self.shapes[item.tkinter_id]
        if item in self.items:
            self.items.remove(item)

    def flush(self):
        """Force display update."""
        self.update()

    def manualUpdate(self):
        """Manual update for compatibility."""
        self.update()

    @staticmethod
    def color_name_to_rgb(color_name: str) -> Tuple[int, int, int]:
        """Convert color names to RGB tuples."""
        color_map = {
            "white": (255, 255, 255),
            "black": (0, 0, 0),
            "red": (255, 0, 0),
            "green": (0, 255, 0),
            "blue": (0, 0, 255),
            "cyan": (0, 255, 255),
            "magenta": (255, 0, 255),
            "yellow": (255, 255, 0),
            "gray": (128, 128, 128),
            "orange": (255, 165, 0)
        }
        return color_map.get(color_name.lower(), (0, 0, 0))  # Default to black

def color_rgb(r: int, g: int, b: int) -> Tuple[int, int, int]:
    """Create color tuple from RGB values."""
    return (r, g, b)
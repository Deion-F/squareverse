"""Main simulation window with grid display and controls."""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import time
import numpy as np
from typing import Optional
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from squareverse.core.grid_world import GridWorld
from squareverse.core.physics_engine import PhysicsEngine


class SimulationWindow:
    """Main simulation window with real-time physics."""
    
    def __init__(self, window_size: int, grid_size: int):
        """
        Initialize the simulation window.
        
        Args:
            window_size: Size of the window in pixels
            grid_size: Number of grid cells per side
        """
        self.window_size = window_size
        self.grid_size = grid_size
        self.cell_size = window_size // grid_size
        self.should_return_to_setup = False
        
        # Core components
        self.grid_world = GridWorld(grid_size, grid_size)
        self.physics_engine = PhysicsEngine()
        
        # Simulation state
        self.running = False
        self.simulation_thread: Optional[threading.Thread] = None
        self.stop_thread = False
        
        # FPS and physics settings
        self.target_fps = 20  # Physics updates per second
        self.physics_interval = 1.0 / self.target_fps  # Time between updates in seconds
        
        # Statistics
        self.fps = 0.0
        self.frame_count = 0
        self.last_fps_update = time.time()
        
        # UI Components
        self.root = tk.Tk()
        self.root.title("SquareVerse - Physics Simulation")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Configure window
        self.root.configure(bg='#1a1a1a')
        
        self._create_widgets()
        self._center_window()

        # Tracking state (initialize before starting display loop)
        self.tracking_mode = False
        self.selecting_for_track = False
        self.tracked_ids = set()
        self.tracked_histories = {}  # id -> list of (x,y)
        self.track_prev_running = False
        self._track_canvas_items = []

        # Start rendering loop
        self._update_display()
    
    def _center_window(self):
        """Center the window on screen."""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'+{x}+{y}')
    
    def _create_widgets(self):
        """Create all UI widgets."""
        # Main container
        main_frame = tk.Frame(self.root, bg='#1a1a1a')
        main_frame.pack(padx=10, pady=10)
        
        # Top info bar
        info_frame = tk.Frame(main_frame, bg='#2a2a2a', relief='flat', bd=0)
        info_frame.pack(fill='x', pady=(0, 10))
        
        info_label = tk.Label(
            info_frame,
            text=f"Grid: {self.grid_size}×{self.grid_size}  |  Cell Size: {self.cell_size}px",
            font=('Helvetica', 10),
            bg='#2a2a2a',
            fg='#00d4ff',
            pady=8
        )
        info_label.pack()
        
        # Canvas for grid display
        canvas_frame = tk.Frame(main_frame, bg='#000000', relief='solid', bd=2)
        canvas_frame.pack(pady=(0, 10))
        
        self.canvas = tk.Canvas(
            canvas_frame,
            width=self.window_size,
            height=self.window_size,
            bg='#0a0a0a',
            highlightthickness=0
        )
        self.canvas.pack()
        
        # Draw initial grid
        self._draw_grid()
        
        # Statistics panel
        stats_frame = tk.Frame(main_frame, bg='#2a2a2a', relief='flat', bd=0)
        stats_frame.pack(fill='x', pady=(0, 10))
        
        self.stats_label = tk.Label(
            stats_frame,
            text="Squares: 0 / 0  |  FPS: 0  |  Status: Stopped",
            font=('Helvetica', 10, 'bold'),
            bg='#2a2a2a',
            fg='#ffffff',
            pady=8
        )
        self.stats_label.pack()
        
        # FPS Control panel
        fps_frame = tk.Frame(main_frame, bg='#2a2a2a', relief='flat', bd=0)
        fps_frame.pack(fill='x', pady=(0, 10))
        
        fps_label = tk.Label(
            fps_frame,
            text="Simulation Speed:",
            font=('Helvetica', 10, 'bold'),
            bg='#2a2a2a',
            fg='#ffffff',
            padx=5
        )
        fps_label.pack(side=tk.LEFT, padx=5)
        
        self.fps_value_label = tk.Label(
            fps_frame,
            text=f"{self.target_fps} FPS",
            font=('Helvetica', 10),
            bg='#2a2a2a',
            fg='#00d4ff',
            width=8
        )
        self.fps_value_label.pack(side=tk.RIGHT, padx=5)
        
        self.fps_slider = tk.Scale(
            fps_frame,
            from_=1,
            to=120,
            orient=tk.HORIZONTAL,
            resolution=1,  # Allow single FPS increments
            showvalue=False,
            bg='#3a3a3a',
            fg='#ffffff',
            troughcolor='#1a1a1a',
            activebackground='#00d4ff',
            highlightthickness=0,
            relief='flat',
            bd=0,
            command=self._update_target_fps
        )
        self.fps_slider.set(self.target_fps)
        self.fps_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Control panel
        control_frame = tk.Frame(main_frame, bg='#1a1a1a')
        control_frame.pack(fill='x')
        
        # Button style configuration
        button_config = {
            'font': ('Helvetica', 10, 'bold'),
            'relief': 'flat',
            'bd': 0,
            'padx': 15,
            'pady': 8,
            'cursor': 'hand2'
        }
        
        # Row 1: Spawn and Start/Stop
        row1_frame = tk.Frame(control_frame, bg='#1a1a1a')
        row1_frame.pack(fill='x', pady=5)
        
        self.spawn_button = tk.Button(
            row1_frame,
            text="🟦 Spawn Squares",
            command=self._spawn_square,
            bg='#0066cc',
            fg='white',
            activebackground='#0088ff',
            activeforeground='white',
            **button_config
        )
        self.spawn_button.pack(side='left', padx=5, expand=True, fill='x')
        
        self.start_stop_button = tk.Button(
            row1_frame,
            text="▶ Start Movement",
            command=self._toggle_simulation,
            bg='#00aa00',
            fg='white',
            activebackground='#00cc00',
            activeforeground='white',
            **button_config
        )
        self.start_stop_button.pack(side='left', padx=5, expand=True, fill='x')
        
        # Row 2: Delete buttons
        row2_frame = tk.Frame(control_frame, bg='#1a1a1a')
        row2_frame.pack(fill='x', pady=5)
        
        self.delete_button = tk.Button(
            row2_frame,
            text="❌ Delete Square",
            command=self._delete_square,
            bg='#cc6600',
            fg='white',
            activebackground='#ff8800',
            activeforeground='white',
            **button_config
        )
        self.delete_button.pack(side='left', padx=5, expand=True, fill='x')
        
        self.delete_all_button = tk.Button(
            row2_frame,
            text="🗑️ Delete All",
            command=self._delete_all_squares,
            bg='#aa0000',
            fg='white',
            activebackground='#cc0000',
            activeforeground='white',
            **button_config
        )
        self.delete_all_button.pack(side='left', padx=5, expand=True, fill='x')
        
        # Row 3: Additional controls
        row3_frame = tk.Frame(control_frame, bg='#1a1a1a')
        row3_frame.pack(fill='x', pady=5)
        
        # Track Movement Button (toggle)
        self.track_button = tk.Button(
            row3_frame,
            text="🔍 Track Movement",
            command=self._toggle_track_mode,
            bg='#444444',
            fg='white',
            activebackground='#666666',
            activeforeground='white',
            **button_config
        )
        self.track_button.pack(side='left', padx=5, expand=True, fill='x')

        # Return to Setup Button
        self.return_button = tk.Button(
            row3_frame,
            text="⚙️ Return to Setup",
            command=self._return_to_setup,
            bg='#555555',
            fg='white',
            activebackground='#777777',
            activeforeground='white',
            **button_config
        )
        self.return_button.pack(side='left', padx=5, expand=True, fill='x')
        
        self.end_button = tk.Button(
            row3_frame,
            text="⏹️ End Simulation",
            command=self._on_close,
            bg='#660000',
            fg='white',
            activebackground='#880000',
            activeforeground='white',
            **button_config
        )
        self.end_button.pack(padx=5, expand=True, fill='x')
    
    def _draw_grid(self):
        """Draw the grid lines on the canvas."""
        # Draw vertical lines
        for i in range(self.grid_size + 1):
            x = i * self.cell_size
            self.canvas.create_line(
                x, 0, x, self.window_size,
                fill='#1a1a1a',
                width=1
            )
        
        # Draw horizontal lines
        for i in range(self.grid_size + 1):
            y = i * self.cell_size
            self.canvas.create_line(
                0, y, self.window_size, y,
                fill='#1a1a1a',
                width=1
            )
    
    def _draw_squares(self):
        """Draw all squares on the canvas."""
        # Clear previous squares (keep grid)
        self.canvas.delete('square')
        
        # Draw each square
        for square in self.grid_world.squares:
            x1 = square.x * self.cell_size + 2
            y1 = square.y * self.cell_size + 2
            x2 = x1 + self.cell_size - 4
            y2 = y1 + self.cell_size - 4
            
            # Draw square with color based on mass (no contrasting border)
            self.canvas.create_rectangle(
                x1, y1, x2, y2,
                fill=square.color,
                outline=square.color,
                width=0,
                tags='square'
            )
            
            # Draw mass label only if the cell is large enough
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            
            # Calculate font size based on cell size
            font_size = max(8, self.cell_size // 4)
            
            # Check if the text would fit in the cell
            text = f"{square.mass:.1f}"
            text_width = len(text) * font_size * 0.6  # Approximate width based on font size
            square_width = self.cell_size - 4  # Account for padding
            
            # Only draw text if it can fit within the square
            if square.stalled:
                # Draw an X to indicate it couldn't move
                offset = max(2, int(self.cell_size * 0.15))
                item1 = self.canvas.create_line(x1+offset, y1+offset, x2-offset, y2-offset, fill='white', width=2, tags='square')
                item2 = self.canvas.create_line(x1+offset, y2-offset, x2-offset, y1+offset, fill='white', width=2, tags='square')
            else:
                if text_width < square_width and self.cell_size >= 12:
                    # Draw mass text (if it fits)
                    self.canvas.create_text(
                        cx, cy,
                        text=text,
                        fill='white',
                        font=('Helvetica', font_size, 'bold'),
                        tags='square'
                    )
            # If this square is being tracked, draw a highlight border
            if square.id in self.tracked_ids:
                self.canvas.create_rectangle(
                    x1-2, y1-2, x2+2, y2+2,
                    outline='yellow', width=2, tags='square'
                )
    
    def _update_statistics(self):
        """Update statistics display."""
        current_squares = self.grid_world.get_square_count()
        max_squares = self.grid_world.get_max_squares()
        status = "Running" if self.running else "Stopped"
        
        self.stats_label.config(
            text=f"Squares: {current_squares} / {max_squares}  |  Actual FPS: {self.fps:.1f}  |  Status: {status}"
        )
    
    def _update_display(self):
        """Update display loop (runs in main thread)."""
        if not self.stop_thread:
            # Draw tracks first so squares are on top
            self._draw_tracks()
            self._draw_squares()
            self._update_statistics()
            
            # Calculate FPS
            self.frame_count += 1
            current_time = time.time()
            if current_time - self.last_fps_update >= 1.0:
                self.fps = self.frame_count / (current_time - self.last_fps_update)
                self.frame_count = 0
                self.last_fps_update = current_time
            
            # Schedule next update (60 FPS target)
            self.root.after(16, self._update_display)
    
    def _spawn_square(self):
        """Spawn multiple squares with random masses."""
        available_space = self.grid_world.get_max_squares() - self.grid_world.get_square_count()
        
        if available_space <= 0:
            messagebox.showwarning(
                "Grid Full",
                "Cannot spawn more squares. Grid is full!"
            )
            return
        
        # Ask how many squares to spawn
        num_squares = simpledialog.askinteger(
            "Spawn Squares",
            f"How many squares would you like to spawn? (1-{available_space}):",
            minvalue=1,
            maxvalue=available_space,
            initialvalue=min(5, available_space)
        )
        
        if num_squares is None:
            return  # User cancelled
            
        # Spawn the requested number of squares with random masses
        spawned_squares = []
        failed_spawns = 0
        
        for _ in range(num_squares):
            # Generate random mass between 0.1 and 10.0
            random_mass = 0.1 + 9.9 * np.random.random()  # Random between 0.1 and 10.0
            
            square = self.grid_world.add_square_random(random_mass)
            if square:
                spawned_squares.append(square)
            else:
                failed_spawns += 1
                break  # Stop if we can't spawn more

        # Initialize histories for newly spawned squares
        for s in spawned_squares:
            if s.id not in self.tracked_histories:
                self.tracked_histories[s.id] = [(s.x, s.y)]
        
        # Show results
        if spawned_squares:
            messagebox.showinfo(
                "Squares Spawned",
                f"Successfully spawned {len(spawned_squares)} squares with random masses."
            )
        else:
            messagebox.showerror(
                "Spawn Failed",
                "Could not find empty positions for the squares."
            )
    
    def _delete_square(self):
        """Enter square deletion mode where user can click squares to delete them."""
        if self.grid_world.get_square_count() == 0:
            messagebox.showwarning("No Squares", "There are no squares to delete!")
            return
        
        # Toggle deletion mode
        if hasattr(self, 'delete_mode') and self.delete_mode:
            # Turn off deletion mode
            self.delete_mode = False
            self.delete_button.config(
                text="❌ Delete Square",
                bg='#cc6600',
                activebackground='#ff8800'
            )
            self.canvas.config(cursor="")
            self.canvas.unbind("<Button-1>")
            messagebox.showinfo("Delete Mode", "Delete mode deactivated.")
        else:
            # Turn on deletion mode
            self.delete_mode = True
            self.delete_button.config(
                text="✅ Done Deleting",
                bg='#00aa00',
                activebackground='#00cc00'
            )
            self.canvas.config(cursor="crosshair")
            self.canvas.bind("<Button-1>", self._handle_canvas_click)
            messagebox.showinfo(
                "Delete Mode", 
                "Delete mode activated. Click on squares to delete them.\n"
                "Click the 'Done Deleting' button when finished."
            )
    
    def _handle_canvas_click(self, event):
        """Handle canvas click in delete mode."""
        if not hasattr(self, 'delete_mode') or not self.delete_mode:
            return
        
        # Convert canvas coordinates to grid coordinates
        grid_x = event.x // self.cell_size
        grid_y = event.y // self.cell_size
        
        # Check if the coordinates are within bounds
        if 0 <= grid_x < self.grid_world.grid_width and 0 <= grid_y < self.grid_world.grid_height:
            # Look for square at this position
            square = self.grid_world.get_square_at(grid_x, grid_y)
            if square:
                # Delete the square
                self.grid_world.remove_square(square.id)
                # No need for a message box for each deletion - just update the display
    
    def _delete_all_squares(self):
        """Delete all squares."""
        if self.grid_world.get_square_count() == 0:
            messagebox.showinfo("No Squares", "There are no squares to delete!")
            return
        
        response = messagebox.askyesno(
            "Confirm Delete All",
            f"Delete all {self.grid_world.get_square_count()} squares?"
        )
        
        if response:
            self.grid_world.remove_all_squares()
            messagebox.showinfo("Success", "All squares deleted.")
    
    def _toggle_simulation(self):
        """Toggle simulation running state."""
        if self.running:
            # Stop simulation
            self.running = False
            self.start_stop_button.config(
                text="▶ Start Movement",
                bg='#00aa00',
                activebackground='#00cc00'
            )
        else:
            # Start simulation
            if self.grid_world.get_square_count() == 0:
                messagebox.showwarning(
                    "No Squares",
                    "Spawn some squares before starting the simulation!"
                )
                return
            
            self.running = True
            self.start_stop_button.config(
                text="⏸ Stop Movement",
                bg='#cc6600',
                activebackground='#ff8800'
            )
            
            # Start physics thread if not already running
            if self.simulation_thread is None or not self.simulation_thread.is_alive():
                self.simulation_thread = threading.Thread(
                    target=self._physics_loop,
                    daemon=True
                )
                self.simulation_thread.start()

    def _toggle_track_mode(self):
        """Toggle the track movement mode: enter selection or clear existing tracks."""
        if self.tracking_mode:
            # Turn off tracking: pause, clear highlights and lines
            self.tracking_mode = False
            self.track_button.config(text="🔍 Track Movement")
            # Stop selecting if active
            if self.selecting_for_track:
                self.selecting_for_track = False
                self.canvas.unbind('<Button-1>')
            # Resume previous running state
            if self.track_prev_running:
                self._toggle_simulation()
                self.track_prev_running = False
            # Clear drawn tracks/highlights
            self._clear_tracks()
            messagebox.showinfo("Tracking", "Tracking cleared.")
        else:
            # Start tracking selection mode: pause simulation and allow clicks
            self.tracking_mode = True
            self.track_button.config(text="⏺️ Done Tracking")
            # Pause simulation if running
            if self.running:
                self.track_prev_running = True
                self._toggle_simulation()
            else:
                self.track_prev_running = False

            # Enable selection mode
            self.selecting_for_track = True
            self.tracked_ids.clear()
            self._clear_tracks()
            self.canvas.config(cursor='crosshair')
            self.canvas.bind('<Button-1>', self._handle_track_click)
            messagebox.showinfo("Track Selection", "Select squares to track by clicking them. Click 'Done Tracking' when finished.")

    def _handle_track_click(self, event):
        """Handle canvas clicks when selecting squares to track."""
        if not self.selecting_for_track:
            return
        grid_x = event.x // self.cell_size
        grid_y = event.y // self.cell_size
        if 0 <= grid_x < self.grid_world.grid_width and 0 <= grid_y < self.grid_world.grid_height:
            square = self.grid_world.get_square_at(grid_x, grid_y)
            if square:
                # Toggle tracking for this square
                if square.id in self.tracked_ids:
                    self.tracked_ids.remove(square.id)
                    if square.id in self.tracked_histories:
                        del self.tracked_histories[square.id]
                else:
                    self.tracked_ids.add(square.id)
                    # initialize history
                    self.tracked_histories.setdefault(square.id, [(square.x, square.y)])
                # Update visuals immediately
                self._draw_squares()

    def _clear_tracks(self):
        """Remove any track lines and reset highlight state (keeps histories if needed)."""
        # Remove track line canvas items
        for item in list(self._track_canvas_items):
            try:
                self.canvas.delete(item)
            except Exception:
                pass
        self._track_canvas_items.clear()
        # No more highlights are drawn automatically in draw; just refresh
        self._draw_squares()

    def _draw_tracks(self):
        """Draw path lines for tracked squares (up to last 10 positions)."""
        # Clear existing track items
        for item in list(self._track_canvas_items):
            try:
                self.canvas.delete(item)
            except Exception:
                pass
        self._track_canvas_items.clear()

        # Draw each tracked history as a polyline
        for sid, history in self.tracked_histories.items():
            if not history or len(history) < 2:
                continue

            # Find the square to get color
            sq = next((s for s in self.grid_world.squares if s.id == sid), None)
            color = sq.color if sq is not None else '#ffffff'

            # Convert history grid positions to canvas coordinates
            coords = []
            for (gx, gy) in history:
                cx = gx * self.cell_size + self.cell_size / 2
                cy = gy * self.cell_size + self.cell_size / 2
                coords.extend([cx, cy])

            # Draw line (lighter, slightly transparent effect via stipple not supported; use dashed)
            item = self.canvas.create_line(*coords, fill=color, width=2, dash=(4, 2), tags='track')
            self._track_canvas_items.append(item)
    
    def _deduplicate_squares(self):
        """Remove duplicate squares at the same position, keeping only one at each position."""
        # Create a dictionary to track squares by position
        pos_dict = {}
        
        # Keep track of which squares to keep
        squares_to_keep = []
        
        # Go through all squares and keep only one per position
        for square in self.grid_world.squares:
            pos = (square.x, square.y)
            
            if pos not in pos_dict:
                # First square at this position, keep it
                pos_dict[pos] = square
                squares_to_keep.append(square)
        
        # Update the grid world with only the kept squares
        self.grid_world.squares = squares_to_keep
        self.grid_world.update_occupied_positions()
    
    def _update_target_fps(self, value):
        """Update the target FPS value."""
        try:
            self.target_fps = float(value)
            self.physics_interval = 1.0 / self.target_fps
            self.fps_value_label.config(text=f"{self.target_fps} FPS")
        except (ValueError, ZeroDivisionError):
            pass
    
    def _physics_loop(self):
        """Physics calculation loop (runs in separate thread)."""
        while not self.stop_thread:
            if self.running:
                # Store the initial count of squares for verification
                initial_count = len(self.grid_world.squares)
                
                # Update physics
                self.physics_engine.update_physics(
                    self.grid_world.squares,
                    self.grid_world.grid_width,
                    self.grid_world.grid_height
                )
                
                # Make sure to update the grid_world's occupied_positions
                self.grid_world.update_occupied_positions()
                
                # Verify square count hasn't changed
                current_count = len(self.grid_world.squares)
                if current_count != initial_count:
                    print(f"Warning: Square count changed from {initial_count} to {current_count}")
                    # This should never happen, but if it does, restore the count
                    # by removing any duplicates at the same position
                    self._deduplicate_squares()
                # Record tracked histories after physics update
                if self.tracked_ids:
                    for s in self.grid_world.squares:
                        if s.id in self.tracked_ids:
                            hist = self.tracked_histories.setdefault(s.id, [])
                            hist.append((s.x, s.y))
                            # Keep only last 10 positions
                            if len(hist) > 10:
                                hist.pop(0)
                
                # Control simulation speed based on target FPS
                time.sleep(self.physics_interval)
            else:
                # Sleep while paused
                time.sleep(0.1)
    
    def _on_close(self):
        """Handle window close event."""
        if self.running:
            response = messagebox.askyesno(
                "Confirm Exit",
                "Simulation is running. Are you sure you want to exit?"
            )
            if not response:
                return
        
        # Stop threads
        self.stop_thread = True
        self.running = False
        
        # Wait for physics thread to finish
        if self.simulation_thread and self.simulation_thread.is_alive():
            self.simulation_thread.join(timeout=1.0)
        
        # Cleanup
        self.grid_world.remove_all_squares()
        
        # Destroy window
        self.root.quit()
        self.root.destroy()
    
    def _return_to_setup(self):
        """Return to setup window by closing current window and signaling return."""
        if self.running:
            response = messagebox.askyesno(
                "Return to Setup",
                "Simulation is running. Return to setup screen?"
            )
            if not response:
                return
        
        # Stop simulation
        self.running = False
        self.stop_thread = True

        # Unbind any temporary bindings
        try:
            self.canvas.unbind('<Button-1>')
        except Exception:
            pass

        # Wait for thread to end
        if self.simulation_thread and self.simulation_thread.is_alive():
            self.simulation_thread.join(timeout=1.0)

        # Cleanup world
        self.grid_world.remove_all_squares()

        # Signal to return to setup
        self.should_return_to_setup = True

        # Destroy window and exit mainloop
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass
    
    def run(self):
        """Start the simulation window and return whether to go back to setup."""
        self.root.mainloop()
        return self.should_return_to_setup


if __name__ == '__main__':
    # Test the simulation window
    sim = SimulationWindow(600, 20)
    sim.run()

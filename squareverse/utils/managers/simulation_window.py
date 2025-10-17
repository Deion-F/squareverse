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
        
        # Core components
        self.grid_world = GridWorld(grid_size, grid_size)
        self.physics_engine = PhysicsEngine()
        
        # Simulation state
        self.running = False
        self.simulation_thread: Optional[threading.Thread] = None
        self.stop_thread = False
        
        # Delete mode state
        self.delete_mode = False
        
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
            highlightthickness=0,
            cursor='arrow'  # Default cursor
        )
        self.canvas.pack()
        
        # Bind canvas click for square deletion
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        
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
        
        # Row 3: End simulation
        row3_frame = tk.Frame(control_frame, bg='#1a1a1a')
        row3_frame.pack(fill='x', pady=5)
        
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
            
            # Draw square with color based on mass
            self.canvas.create_rectangle(
                x1, y1, x2, y2,
                fill=square.color,
                outline='#ffffff',
                width=2,
                tags='square'
            )
            
            # Draw mass label
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            self.canvas.create_text(
                cx, cy,
                text=f"{square.mass:.1f}",
                fill='white',
                font=('Helvetica', max(8, self.cell_size // 4), 'bold'),
                tags='square'
            )
    
    def _update_statistics(self):
        """Update statistics display."""
        current_squares = self.grid_world.get_square_count()
        max_squares = self.grid_world.get_max_squares()
        status = "Running" if self.running else "Stopped"
        
        self.stats_label.config(
            text=f"Squares: {current_squares} / {max_squares}  |  FPS: {self.fps:.1f}  |  Status: {status}"
        )
    
    def _update_display(self):
        """Update display loop (runs in main thread)."""
        if not self.stop_thread:
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
    
    def _on_canvas_click(self, event):
        """Handle canvas click events for square deletion."""
        if not self.delete_mode:
            return
            
        # Convert pixel coordinates to grid coordinates
        grid_x = event.x // self.cell_size
        grid_y = event.y // self.cell_size
        
        # Find square at this position
        square = self.grid_world.get_square_at(grid_x, grid_y)
        
        if square:
            # Found a square, delete it
            self.grid_world.remove_square(square.id)
            messagebox.showinfo("Success", f"Square {square.id} deleted.")
            
            # Exit delete mode
            self._exit_delete_mode()
        else:
            # No square at click position
            messagebox.showinfo("No Square", "No square at this position. Try again or click 'Delete Square' button to cancel.")
    
    def _exit_delete_mode(self):
        """Exit delete mode."""
        self.delete_mode = False
        self.canvas.config(cursor='arrow')  # Reset cursor
        self.delete_button.config(
            text="❌ Delete Square",
            bg='#cc6600',
            activebackground='#ff8800'
        )
    
    def _delete_square(self):
        """Enter delete mode to select a square to delete."""
        if self.grid_world.get_square_count() == 0:
            messagebox.showwarning("No Squares", "There are no squares to delete!")
            return
            
        # If already in delete mode, exit it
        if self.delete_mode:
            self._exit_delete_mode()
            return
            
        # Enter delete mode
        self.delete_mode = True
        self.canvas.config(cursor='crosshair')  # Change cursor to indicate delete mode
        self.delete_button.config(
            text="🔄 Cancel Delete",
            bg='#888888',
            activebackground='#aaaaaa'
        )
        
        messagebox.showinfo(
            "Delete Mode", 
            "Click on a square to delete it.\nClick the 'Cancel Delete' button to exit delete mode."
        )
    
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
    
    def _physics_loop(self):
        """Physics calculation loop (runs in separate thread)."""
        while not self.stop_thread:
            if self.running:
                # Update physics
                self.physics_engine.update_physics(
                    self.grid_world.squares,
                    self.grid_world.grid_width,
                    self.grid_world.grid_height
                )
                
                # Control simulation speed (20 updates per second)
                time.sleep(0.05)
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
    
    def run(self):
        """Start the simulation window."""
        self.root.mainloop()


if __name__ == '__main__':
    # Test the simulation window
    sim = SimulationWindow(600, 20)
    sim.run()

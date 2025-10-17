"""Initial setup window for simulation configuration."""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Tuple


class SetupWindow:
    """Modern UI for initial simulation setup."""
    
    def __init__(self):
        """Initialize the setup window."""
        self.root = tk.Tk()
        self.root.title("SquareVerse - Simulation Setup")
        self.root.geometry("500x400")
        self.root.resizable(False, False)
        
        # Configure modern styling
        self.root.configure(bg='#2b2b2b')
        
        self.window_size = tk.IntVar(value=600)
        self.grid_size = tk.IntVar()  # Initially empty
        self.valid_grid_sizes = []  # Will be populated based on window size
        
        self.result: Optional[Tuple[int, int]] = None
        
        self._create_widgets()
        self._center_window()
    
    def _center_window(self):
        """Center the window on screen."""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
    
    def _create_widgets(self):
        """Create all UI widgets."""
        # Title
        title_frame = tk.Frame(self.root, bg='#2b2b2b')
        title_frame.pack(pady=20)
        
        title_label = tk.Label(
            title_frame,
            text="🟦 SquareVerse Physics Simulator",
            font=('Helvetica', 18, 'bold'),
            bg='#2b2b2b',
            fg='#00d4ff'
        )
        title_label.pack()
        
        subtitle_label = tk.Label(
            title_frame,
            text="Configure your simulation",
            font=('Helvetica', 10),
            bg='#2b2b2b',
            fg='#aaaaaa'
        )
        subtitle_label.pack()
        
        # Main content frame
        content_frame = tk.Frame(self.root, bg='#2b2b2b')
        content_frame.pack(pady=20, padx=40, fill='both', expand=True)
        
        # Window Size Section with 50px increments
        self._create_section(
            content_frame,
            "Window Size (pixels)",
            self.window_size,
            list(range(100, 1050, 50)),  # 100 to 1000 in 50px increments
            0
        )
        
        # Grid Size Section - Will be updated after window size is selected
        self.grid_section_frame = tk.Frame(content_frame, bg='#2b2b2b')
        self.grid_section_frame.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        
        # Grid Size Label
        self.grid_label = tk.Label(
            self.grid_section_frame,
            text="Grid Size (cells per side)",
            font=('Helvetica', 11, 'bold'),
            bg='#2b2b2b',
            fg='#ffffff'
        )
        self.grid_label.grid(row=0, column=0, sticky='w', pady=(10, 5))
        
        # Grid Size Value Label
        self.grid_value_label = tk.Label(
            self.grid_section_frame,
            text="Select window size first",
            font=('Helvetica', 11, 'bold'),
            bg='#2b2b2b',
            fg='#aaaaaa',
            width=20
        )
        self.grid_value_label.grid(row=0, column=1, sticky='e', pady=(10, 5))
        
        # Grid Size Dropdown Frame
        self.grid_dropdown_frame = tk.Frame(self.grid_section_frame, bg='#2b2b2b')
        self.grid_dropdown_frame.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        
        # Initially create empty dropdown
        self._update_grid_sizes()
        
        # Info label
        info_frame = tk.Frame(content_frame, bg='#3a3a3a', relief='flat', bd=0)
        info_frame.grid(row=2, column=0, columnspan=2, pady=20, sticky='ew')
        
        info_label = tk.Label(
            info_frame,
            text="💡 Grid size must divide evenly into window size",
            font=('Helvetica', 9),
            bg='#3a3a3a',
            fg='#ffaa00',
            pady=10
        )
        info_label.pack()
        
        # Start Button
        start_button = tk.Button(
            content_frame,
            text="Start Simulation",
            command=self._start_simulation,
            font=('Helvetica', 12, 'bold'),
            bg='#00aa00',
            fg='white',
            activebackground='#00cc00',
            activeforeground='white',
            relief='flat',
            bd=0,
            padx=20,
            pady=10,
            cursor='hand2'
        )
        start_button.grid(row=3, column=0, columnspan=2, pady=10)
        
        # Bind validation to changes
        self.window_size.trace('w', self._validate_input)
        self.grid_size.trace('w', self._validate_input)
    
    def _create_section(self, parent, label_text, variable, values, row):
        """Create a configuration section with label and slider."""
        # Label
        label = tk.Label(
            parent,
            text=label_text,
            font=('Helvetica', 11, 'bold'),
            bg='#2b2b2b',
            fg='#ffffff'
        )
        label.grid(row=row, column=0, sticky='w', pady=(10, 5))
        
        # Value display
        value_label = tk.Label(
            parent,
            text=str(variable.get()),
            font=('Helvetica', 11, 'bold'),
            bg='#2b2b2b',
            fg='#00d4ff',
            width=6
        )
        value_label.grid(row=row, column=1, sticky='e', pady=(10, 5))
        
        # Slider frame
        slider_frame = tk.Frame(parent, bg='#2b2b2b')
        slider_frame.grid(row=row+1, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        
        # Create custom scale
        scale = tk.Scale(
            slider_frame,
            from_=min(values),
            to=max(values),
            orient='horizontal',
            variable=variable,
            showvalue=False,
            bg='#3a3a3a',
            fg='#ffffff',
            troughcolor='#1a1a1a',
            activebackground='#00d4ff',
            highlightthickness=0,
            relief='flat',
            bd=0,
            length=400
        )
        scale.pack(fill='x')
        
        # Update value label when slider changes
        def update_label(*args):
            value_label.config(text=str(variable.get()))
        
        variable.trace('w', update_label)
    
    def _get_valid_grid_sizes(self, window_size):
        """Get list of valid grid sizes for a given window size."""
        valid_sizes = []
        
        # Check all possible factors from 2 to 100
        for size in [2, 4, 5, 8, 10, 20, 25, 40, 50, 100]:
            if size <= 100 and window_size % size == 0:
                valid_sizes.append(size)
        
        return valid_sizes
    
    def _update_grid_sizes(self, *args):
        """Update grid size dropdown with valid options based on window size."""
        window_size = self.window_size.get()
        self.valid_grid_sizes = self._get_valid_grid_sizes(window_size)
        
        # Clear previous dropdown if it exists
        for widget in self.grid_dropdown_frame.winfo_children():
            widget.destroy()
            
        if not self.valid_grid_sizes:
            # No valid grid sizes
            self.grid_value_label.config(
                text="No valid grid sizes",
                fg='#ff5555'
            )
            return
            
        # Create new dropdown
        self.grid_value_label.config(
            text="Select grid size:",
            fg='#00d4ff'
        )
        
        # Create dropdown menu for grid size selection
        self.grid_dropdown = ttk.Combobox(
            self.grid_dropdown_frame, 
            values=self.valid_grid_sizes,
            state="readonly",
            width=10,
            font=('Helvetica', 10)
        )
        
        # Default to the middle option
        middle_index = len(self.valid_grid_sizes) // 2
        self.grid_dropdown.current(middle_index)
        self.grid_size.set(self.valid_grid_sizes[middle_index])
        
        # Bind selection event
        def on_grid_select(event):
            selected = int(self.grid_dropdown.get())
            self.grid_size.set(selected)
        
        self.grid_dropdown.bind("<<ComboboxSelected>>", on_grid_select)
        self.grid_dropdown.pack(fill='x', padx=5, pady=10)
    
    def _validate_input(self, *args):
        """Update grid size options when window size changes."""
        # Always update grid sizes when any value changes
        # This will be called when window_size changes
        self._update_grid_sizes()
    
    def _start_simulation(self):
        """Validate and start the simulation."""
        window = self.window_size.get()
        
        # Make sure a grid size is selected
        if not hasattr(self, 'grid_dropdown') or not self.grid_dropdown.get():
            messagebox.showerror(
                "Invalid Configuration",
                "Please select a grid size."
            )
            return
            
        grid = int(self.grid_dropdown.get())
        
        # Double-check that the grid size is valid
        if window % grid != 0:
            messagebox.showerror(
                "Invalid Configuration",
                f"Grid size ({grid}) must divide evenly into window size ({window}).\n\n"
                f"Please select a valid grid size."
            )
            return
        
        self.result = (window, grid)
        self.root.quit()
        self.root.destroy()
    
    def show(self) -> Optional[Tuple[int, int]]:
        """
        Show the setup window and wait for user input.
        
        Returns:
            Tuple of (window_size, grid_size) or None if cancelled
        """
        self.root.mainloop()
        return self.result


if __name__ == '__main__':
    # Test the setup window
    setup = SetupWindow()
    result = setup.show()
    if result:
        print(f"Window Size: {result[0]}px, Grid Size: {result[1]} cells")
    else:
        print("Setup cancelled")

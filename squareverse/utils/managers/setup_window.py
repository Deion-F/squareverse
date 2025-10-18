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
        self.root.geometry("500x450")
        self.root.resizable(False, False)
        
        # Configure modern styling
        self.root.configure(bg='#2b2b2b')
        
        self.window_size = tk.IntVar(value=600)
        self.grid_size = tk.IntVar(value=20)
        self.valid_grid_sizes = []  # Will be populated based on window size
        self.grid_size_dropdown = None  # Will be created in _create_grid_size_section
        
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
        
        # Create a section frame for window size
        window_size_section = tk.LabelFrame(content_frame, text="Window Size", bg='#2b2b2b', fg='#ffffff', font=('Helvetica', 11, 'bold'))
        window_size_section.grid(row=0, column=0, columnspan=2, sticky='ew', padx=5, pady=10)
        
        # Create the Window Size Section
        self._create_window_size_section(
            window_size_section,
            "Window Size (pixels)",
            self.window_size,
            list(range(100, 1050, 50)),  # 50px increments from 100 to 1000
            0  # Row in the window size section
        )
        
        # Create a section frame for grid size
        grid_size_section = tk.LabelFrame(content_frame, text="Grid Size", bg='#2b2b2b', fg='#ffffff', font=('Helvetica', 11, 'bold'))
        grid_size_section.grid(row=1, column=0, columnspan=2, sticky='ew', padx=5, pady=10)
        
        # First create the Grid Size Section
        self.grid_size_frame = grid_size_section
        self._create_grid_size_section(
            self.grid_size_frame,
            "Cells per side",
            self.grid_size,
            0  # Row in the grid size section
        )
        
        # Info label
        info_frame = tk.Frame(content_frame, bg='#3a3a3a', relief='flat', bd=0)
        info_frame.grid(row=2, column=0, columnspan=2, pady=15, sticky='ew')
        
        info_label = tk.Label(
            info_frame,
            text="💡 Grid size must divide evenly into window size",
            font=('Helvetica', 9),
            bg='#3a3a3a',
            fg='#ffaa00',
            pady=8
        )
        info_label.pack()
        
        # Start Button
        button_frame = tk.Frame(content_frame, bg='#2b2b2b')
        button_frame.grid(row=3, column=0, columnspan=2, pady=15)
        
        start_button = tk.Button(
            button_frame,
            text="Start Simulation",
            command=self._start_simulation,
            font=('Helvetica', 12, 'bold'),
            bg='#00aa00',
            fg='white',
            activebackground='#00cc00',
            activeforeground='white',
            relief='flat',
            bd=0,
            padx=30,
            pady=10,
            cursor='hand2'
        )
        start_button.pack()
        
        # No need for additional validation bindings as
        # validation is handled in the window_size update and grid size dropdown
    
    def _create_window_size_section(self, parent, label_text, variable, values, row):
        """Create a window size configuration section with 50px increment slider."""
        # Main container for this section
        main_frame = tk.Frame(parent, bg='#2b2b2b')
        main_frame.pack(fill='x', padx=10, pady=5)
        
        # Value display and controls row
        controls_frame = tk.Frame(main_frame, bg='#2b2b2b')
        controls_frame.pack(fill='x')
        
        # Current value display
        value_label = tk.Label(
            controls_frame,
            text=str(variable.get()),
            font=('Helvetica', 12, 'bold'),
            bg='#2b2b2b',
            fg='#00d4ff',
            width=6
        )
        value_label.pack(side='right', padx=5)
        
        # "px" label
        px_label = tk.Label(
            controls_frame,
            text="px",
            font=('Helvetica', 11),
            bg='#2b2b2b',
            fg='#ffffff'
        )
        px_label.pack(side='right', padx=(0, 5))
        
        # Slider frame
        slider_frame = tk.Frame(main_frame, bg='#2b2b2b')
        slider_frame.pack(fill='x', pady=10)
        
        # Create custom scale with snapping behavior
        scale = tk.Scale(
            slider_frame,
            from_=min(values),
            to=max(values),
            orient='horizontal',
            variable=variable,
            showvalue=False,  # No need to show value as we have a dedicated label
            bg='#3a3a3a',
            fg='#ffffff',
            troughcolor='#1a1a1a',
            activebackground='#00d4ff',
            highlightthickness=0,  # Remove highlight 
            relief='flat',  # Clean appearance
            bd=0,
            length=350,  # Slightly smaller to fit better
            resolution=50  # Snap to 50px increments
        )
        scale.pack(fill='x')
        
        # Update value label when slider changes and update grid size options
        def update_window_size(*args):
            current_size = variable.get()
            # Ensure it's a multiple of 50
            rounded_size = round(current_size / 50) * 50
            if current_size != rounded_size:
                variable.set(rounded_size)
            
            value_label.config(text=str(rounded_size))
            
            # Update valid grid sizes
            self._update_valid_grid_sizes(rounded_size)
        
        variable.trace('w', update_window_size)
        # Initialize valid grid sizes
        self._update_valid_grid_sizes(variable.get())
        
    def _create_grid_size_section(self, parent, label_text, variable, row):
        """Create a grid size configuration section with dropdown based on window size."""
        # Main container for this section
        main_frame = tk.Frame(parent, bg='#2b2b2b')
        main_frame.pack(fill='x', padx=10, pady=10)
        
        # Controls layout
        controls_frame = tk.Frame(main_frame, bg='#2b2b2b')
        controls_frame.pack(fill='x')
        
        # Label
        label = tk.Label(
            controls_frame,
            text=label_text,
            font=('Helvetica', 11),
            bg='#2b2b2b',
            fg='#ffffff'
        )
        label.pack(side='left', padx=(0, 10))
        
        # Create dropdown for grid size selection
        self.grid_size_dropdown = ttk.Combobox(
            controls_frame,
            textvariable=variable,
            state='readonly',
            width=5,
            font=('Helvetica', 10)
        )
        
        # Style the combobox
        style = ttk.Style()
        style.theme_use('default')
        style.configure('TCombobox', 
                        background='#3a3a3a',
                        fieldbackground='#3a3a3a',
                        foreground='#00d4ff',
                        arrowcolor='#00d4ff')
        
        self.grid_size_dropdown.pack(side='right')
        
    def _update_valid_grid_sizes(self, window_size):
        """Update the valid grid sizes based on the window size."""
        self.valid_grid_sizes = []
        
        # Find all possible divisors of the window size
        for i in range(1, window_size + 1):
            if window_size % i == 0 and i <= 100:  # Limit to maximum 100 cells per side
                self.valid_grid_sizes.append(i)
        
        # Update the dropdown menu with valid options if it exists
        if self.grid_size_dropdown is not None:
            self.grid_size_dropdown['values'] = self.valid_grid_sizes
            
            # Select the first valid grid size if the current one isn't valid
            if self.grid_size.get() not in self.valid_grid_sizes and self.valid_grid_sizes:
                self.grid_size.set(self.valid_grid_sizes[0])
    
    def _validate_input(self, *args):
        """Validate the grid size selection."""
        # This is now handled automatically by the dropdown
        # which only shows valid grid sizes for the selected window size
        pass
    
    def _start_simulation(self):
        """Validate and start the simulation."""
        window = self.window_size.get()
        grid = self.grid_size.get()
        
        if window % grid != 0:
            messagebox.showerror(
                "Invalid Configuration",
                f"Grid size ({grid}) must divide evenly into window size ({window}).\n\n"
                f"Window size {window} ÷ Grid size {grid} = {window/grid:.2f}\n\n"
                f"Please adjust your settings."
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

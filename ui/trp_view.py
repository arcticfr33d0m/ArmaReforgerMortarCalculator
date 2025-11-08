import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
import json
from utils import format_grid_10_digit

class TRPSelectDialog(tk.Toplevel):
    def __init__(self, parent, title, valid_trps_data, is_dark_mode):
        super().__init__(parent)
        self.title(title)
        self.result = None # To store the selected TRP data
        self.transient(parent)
        self.valid_trps_data = valid_trps_data # Store valid_trps_data as an instance variable

        bg_color = "#252526" if is_dark_mode else "SystemButtonFace"
        fg_color = "#00FF00" if is_dark_mode else "black"
        self.configure(bg=bg_color)

        # Treeview to display valid TRPs
        tree_frame = ttk.Frame(self)
        tree_frame.pack(padx=10, pady=10, fill="both", expand=True)

        columns = ("Grid", "Elevation", "Name/ID")
        self.trp_tree = ttk.Treeview(tree_frame, columns=columns, show="headings")
        self.trp_tree.heading("Grid", text="Grid")
        self.trp_tree.heading("Elevation", text="Elevation")
        self.trp_tree.heading("Name/ID", text="Name/ID")
        
        self.trp_tree.column("Grid", width=100, anchor="center")
        self.trp_tree.column("Elevation", width=70, anchor="center")
        self.trp_tree.column("Name/ID", width=150, anchor="w")
        
        self.trp_tree.pack(side="left", fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.trp_tree.yview)
        self.trp_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        # Populate the treeview
        for i, trp_data in enumerate(self.valid_trps_data): # Now self.valid_trps_data contains full TRP dicts
            self.trp_tree.insert("", "end", iid=str(i), values=(
                trp_data['grid'],
                f"{trp_data['elev']:.1f}",
                trp_data['name']
            ))
        
        # Bind double click to select
        self.trp_tree.bind("<Double-1>", self.on_double_click)
        self.trp_tree.bind("<MouseWheel>", self._on_mousewheel) # Bind mouse wheel to treeview

        # Buttons
        button_frame = ttk.Frame(self)
        button_frame.pack(pady=5)
        select_button = ttk.Button(button_frame, text="Select TRP", command=self.on_select)
        select_button.pack(side="left", padx=10)
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self.destroy)
        cancel_button.pack(side="left", padx=10)

        self.update_idletasks()
        parent_x, parent_y = parent.winfo_x(), parent.winfo_y()
        parent_width, parent_height = parent.winfo_width(), parent.winfo_height()
        dialog_width, dialog_height = 400, 300 # Fixed size for the dialog
        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2
        self.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
        
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.wait_window()

    def _on_mousewheel(self, event):
        self.trp_tree.yview_scroll(int(-1*(event.delta/120)), "units")
        return "break" # Stop event propagation

    def on_double_click(self, event):
        self.on_select()

    def on_select(self):
        selected_item = self.trp_tree.selection()
        if selected_item:
            index = self.trp_tree.index(selected_item[0])
            self.result = self.valid_trps_data[index] # Access self.valid_trps_data
            self.destroy()

class TRPView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding="10")
        self.app = app
        self.pack(fill="both", expand=True)

        # Input Frame for new TRPs
        input_frame = ttk.LabelFrame(self, text="Add New TRP")
        input_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(input_frame, text="Grid:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.grid_entry = ttk.Entry(input_frame, width=15)
        self.grid_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

        ttk.Label(input_frame, text="Elevation (m):").grid(row=0, column=2, padx=5, pady=2, sticky="w")
        self.elev_entry = ttk.Entry(input_frame, width=10)
        self.elev_entry.grid(row=0, column=3, padx=5, pady=2, sticky="ew")

        ttk.Label(input_frame, text="Name/ID:").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.name_entry = ttk.Entry(input_frame, width=20)
        self.name_entry.grid(row=1, column=1, columnspan=3, padx=5, pady=2, sticky="ew")

        add_button = ttk.Button(input_frame, text="Add TRP", command=self.add_trp)
        add_button.grid(row=2, column=0, columnspan=4, pady=5)

        # TRP List Display
        list_frame = ttk.LabelFrame(self, text="Target Reference Points")
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.trp_tree = ttk.Treeview(list_frame, columns=("Grid", "Elevation", "Name/ID", "Status"), show="headings")
        self.trp_tree.heading("Grid", text="Grid")
        self.trp_tree.heading("Elevation", text="Elevation")
        self.trp_tree.heading("Name/ID", text="Name/ID")
        self.trp_tree.heading("Status", text="Status")
        
        self.trp_tree.column("Grid", width=100, anchor="center")
        self.trp_tree.column("Elevation", width=70, anchor="center")
        self.trp_tree.column("Name/ID", width=120, anchor="w")
        self.trp_tree.column("Status", width=100, anchor="center")
        
        self.trp_tree.pack(fill="both", expand=True)

        # Scrollbar for Treeview
        scrollbar = ttk.Scrollbar(self.trp_tree, orient="vertical", command=self.trp_tree.yview)
        self.trp_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        
        # Bind selection event to display details
        self.trp_tree.bind("<<TreeviewSelect>>", self.on_trp_selected)

        # TRP Details Display
        self.details_frame = ttk.LabelFrame(self, text="Selected TRP Details")
        self.details_frame.pack(fill="x", padx=10, pady=5)

        self.detail_grid_label = ttk.Label(self.details_frame, text="Grid: ")
        self.detail_grid_label.grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.detail_elev_label = ttk.Label(self.details_frame, text="Elevation: ")
        self.detail_elev_label.grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.detail_name_label = ttk.Label(self.details_frame, text="Name/ID: ")
        self.detail_name_label.grid(row=2, column=0, padx=5, pady=2, sticky="w")
        self.detail_status_label = ttk.Label(self.details_frame, text="Status: ")
        self.detail_status_label.grid(row=3, column=0, padx=5, pady=2, sticky="w")

        # Buttons for list management
        button_frame = ttk.Frame(self)
        button_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(button_frame, text="Remove Selected TRP", command=self.remove_selected_trp).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Clear All TRPs", command=self.clear_all_trps).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Calculate All TRPs", command=self.calculate_all_trps).pack(side="right", padx=5)
        ttk.Button(button_frame, text="Save TRP List", command=self.save_trp_list).pack(side="right", padx=5)
        ttk.Button(button_frame, text="Load File", command=self.app.load_file_smart).pack(side="right", padx=5)

        self.refresh_trp_list() # Initial population

    def add_trp(self):
        grid = self.grid_entry.get()
        elev = self.elev_entry.get()
        name = self.name_entry.get()

        if not grid or not elev:
            messagebox.showerror("Input Error", "Grid and Elevation are required.")
            return

        try:
            float(elev) # Validate elevation is a number
        except ValueError:
            messagebox.showerror("Input Error", "Elevation must be a number.")
            return

        self.app.state.add_trp()
        new_trp_vars = self.app.state.get_trp_vars(len(self.app.state.trp_input_vars) - 1)
        new_trp_vars['grid'].set(format_grid_10_digit(grid))
        new_trp_vars['elev'].set(float(elev))
        new_trp_vars['name'].set(name if name else f"TRP {len(self.app.state.trp_input_vars)}")
        new_trp_vars['status'].set("Pending") # Initialize status
        
        self.grid_entry.delete(0, tk.END)
        self.elev_entry.delete(0, tk.END)
        self.name_entry.delete(0, tk.END)
        self.refresh_trp_list()

    def remove_selected_trp(self):
        selected_items = self.trp_tree.selection()
        if not selected_items:
            messagebox.showinfo("Selection", "No TRP selected to remove.")
            return

        # Remove from state_manager and then refresh UI
        for item_id in selected_items:
            index = self.trp_tree.index(item_id)
            if 0 <= index < len(self.app.state.trp_input_vars):
                del self.app.state.trp_input_vars[index]
        self.refresh_trp_list()

    def clear_all_trps(self):
        if messagebox.askyesno("Clear All", "Are you sure you want to clear all TRPs?"):
            self.app.state.clear_trps()
            self.refresh_trp_list()

    def refresh_trp_list(self):
        # Clear existing items in the Treeview
        for item in self.trp_tree.get_children():
            self.trp_tree.delete(item)

        # Populate Treeview from state_manager
        for i, trp_vars in enumerate(self.app.state.trp_input_vars):
            status = trp_vars['status'].get()
            tags = ()
            if "Out of Range" in status or "Error" in status or "No Solution" in status:
                tags = ('out_of_range',) # Apply a tag for styling
            elif "Valid" in status or "Solution" in status:
                tags = ('valid_solution',)

            self.trp_tree.insert("", "end", iid=str(i), values=(
                trp_vars['grid'].get(),
                trp_vars['elev'].get(),
                trp_vars['name'].get(),
                status # Display status
            ), tags=tags)
        
        # The tags will be configured in apply_theme based on the current theme.

    def calculate_all_trps(self):
        if not self.app.state.trp_input_vars:
            messagebox.showinfo("No TRPs", "Please add TRPs to the list before calculating.")
            return
        self.app.calculate_trps_from_list()

    def save_trp_list(self):
        """Saves the current list of TRPs to a JSON file."""
        if not self.app.state.trp_input_vars:
            messagebox.showinfo("No TRPs", "No TRPs to save.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Save TRP List As..."
        )
        if not file_path:
            return

        try:
            trp_data_to_save = []
            for trp_vars in self.app.state.trp_input_vars:
                trp_data_to_save.append({
                    "grid": trp_vars['grid'].get(),
                    "elev": trp_vars['elev'].get(),
                    "name": trp_vars['name'].get(),
                    "status": trp_vars['status'].get()
                })

            with open(file_path, 'w') as f:
                json.dump(trp_data_to_save, f, indent=4)
            messagebox.showinfo("Success", f"TRP list saved to {file_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save TRP list: {e}")

    def load_valid_trp_to_main(self):
        all_trps_data = []
        for trp_vars in self.app.state.trp_input_vars:
            all_trps_data.append({
                'grid': trp_vars['grid'].get(),
                'elev': trp_vars['elev'].get(),
                'name': trp_vars['name'].get(),
                'status': trp_vars['status'].get()
            })

        if not all_trps_data:
            messagebox.showinfo("No TRPs", "No TRPs found in the list to load to Main tab.")
            return

        dialog = TRPSelectDialog(self.app, "Select TRP from List", all_trps_data, self.app.is_dark_mode)
        selected_trp = dialog.result

        if selected_trp:
            # Update main UI's TRP input fields
            self.app.state.trp_grid_var.set(selected_trp['grid'])
            self.app.state.trp_elev_var.set(selected_trp['elev'])
            self.app.state.targeting_mode_var.set("Grid") # Ensure Grid mode is selected
            self.app.on_targeting_mode_change() # Update UI based on mode change
            self.app.notebook.select(0) # Switch to Main tab
            messagebox.showinfo("TRP Loaded", f"TRP '{selected_trp['name']}' loaded to Main tab.")
            self.app.calculate_all() # Auto-calculate after loading
    
    def load_trp_list_from_data(self, loaded_trps):
        """Loads a list of TRPs from provided data (used by load_file_smart)."""
        if not isinstance(loaded_trps, list):
            messagebox.showerror("Error", "Invalid TRP list format. Expected a list of TRP objects.")
            return

        self.app.state.clear_trps() # Clear existing TRPs

        for trp_data in loaded_trps:
            if all(key in trp_data for key in ['grid', 'elev', 'name', 'status']):
                self.app.state.add_trp()
                new_trp_vars = self.app.state.get_trp_vars(len(self.app.state.trp_input_vars) - 1)
                new_trp_vars['grid'].set(trp_data['grid'])
                new_trp_vars['elev'].set(trp_data['elev'])
                new_trp_vars['name'].set(trp_data['name'])
                new_trp_vars['status'].set(trp_data['status'])
            else:
                messagebox.showwarning("Load Warning", f"Skipped invalid TRP entry: {trp_data}. Missing one or more of 'grid', 'elev', 'name', 'status'.")

        self.refresh_trp_list()
        messagebox.showinfo("Success", f"Loaded {len(self.app.state.trp_input_vars)} TRPs.")

    def on_trp_selected(self, event):
        selected_items = self.trp_tree.selection()
        if selected_items:
            item_id = selected_items[0]
            index = self.trp_tree.index(item_id)
            if 0 <= index < len(self.app.state.trp_input_vars):
                selected_trp_vars = self.app.state.get_trp_vars(index)
                self.detail_grid_label.config(text=f"Grid: {selected_trp_vars['grid'].get()}")
                self.detail_elev_label.config(text=f"Elevation: {selected_trp_vars['elev'].get():.1f} m")
                self.detail_name_label.config(text=f"Name/ID: {selected_trp_vars['name'].get()}")
                self.detail_status_label.config(text=f"Status: {selected_trp_vars['status'].get()}")
        else:
            self.detail_grid_label.config(text="Grid: ")
            self.detail_elev_label.config(text="Elevation: ")
            self.detail_name_label.config(text="Name/ID: ")
            self.detail_status_label.config(text="Status: ")
            
    def apply_theme(self):
        # This method will be called by the main app to apply theme changes
        # Update Treeview colors based on theme
        if self.app.is_dark_mode:
            self.app.style.configure("Treeview", background="#3C3C3C", fieldbackground="#3C3C3C")
            self.app.style.map("Treeview",
                                background=[("selected", "#4a4a4a")],
                                foreground=[("selected", "white")]) # Keep selected text white for visibility
            self.app.style.configure("Treeview.Heading", background="#252526", foreground="#00FF00")
            # Configure tags for styling in dark mode
            self.trp_tree.tag_configure('out_of_range', foreground='red')
            self.trp_tree.tag_configure('valid_solution', foreground='#00FF00') # Vibrant green for dark mode
            
            self.app.style.layout("TRPDetails.TLabelFrame", [('TLabelframe.border', {'sticky': 'nswe', 'border': '1', 'children': [('TLabelframe.padding', {'sticky': 'nswe', 'children': [('TLabelframe.label', {'sticky': 'nw'}), ('TLabelframe.contents', {'sticky': 'nswe'})]})]})])
            self.app.style.configure("TRPDetails.TLabelFrame", background="#252526", bordercolor="#3C3C3C", relief="solid")
            self.app.style.configure("TRPDetails.TLabelFrame.Label", background="#252526", foreground="#00FF00", font=("Consolas", 10, "bold"))
            self.app.style.configure("TRPDetails.TLabel", background="#252526", foreground="#00FF00", font=("Consolas", 10))
            self.app.update_idletasks() # Force update to ensure style is registered
            self.details_frame.config(style="TRPDetails.TLabelFrame")
            for child in self.details_frame.winfo_children():
                if isinstance(child, ttk.Label):
                    child.config(style="TRPDetails.TLabel")
        else:
            self.app.style.layout("TRPDetails.TLabelFrame", [('TLabelframe.border', {'sticky': 'nswe', 'border': '1', 'children': [('TLabelframe.padding', {'sticky': 'nswe', 'children': [('TLabelframe.label', {'sticky': 'nw'}), ('TLabelframe.contents', {'sticky': 'nswe'})]})]})])
            self.app.style.configure("TRPDetails.TLabelFrame", background="SystemButtonFace", bordercolor="SystemButtonFace", relief="solid")
            self.app.style.configure("TRPDetails.TLabelFrame.Label", background="SystemButtonFace", foreground="black", font=("Consolas", 10, "bold"))
            self.app.style.configure("TRPDetails.TLabel", background="SystemButtonFace", foreground="black", font=("Consolas", 10))
            self.app.update_idletasks() # Force update to ensure style is registered
            self.details_frame.config(style="TRPDetails.TLabelFrame")
            for child in self.details_frame.winfo_children():
                if isinstance(child, ttk.Label):
                    child.config(style="TRPDetails.TLabel")
        self.refresh_trp_list() # Refresh to apply new colors
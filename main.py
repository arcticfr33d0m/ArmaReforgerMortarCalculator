import tkinter as tk
import json
import os
import queue
import threading
from tkinter import ttk, messagebox, filedialog, simpledialog
from PIL import Image, ImageTk
import math

from ballistics import BALLISTIC_DATA, MILS_PER_REVOLUTION
from calculations import (
    parse_grid,
    calculate_target_coords,
    find_valid_solutions,
    check_target_on_mortar_fo_axis,
    check_danger_close,
    calculate_new_fo_data,
)
from mission_log import MissionLog
from config.config_manager import ConfigManager
from config.theme_manager import ThemeManager
from state_manager import StateManager
from ui.map_view import MapView
from ui.settings_view import SettingsView
from ui.fire_mission_planner_view import FireMissionPlannerView, ListSelectDialog # Import ListSelectDialog
from ui.trp_view import TRPView
from worker import worker_thread
from dev_log import DevLog

class CustomDialog(tk.Toplevel):
    def __init__(self, parent, title, message, is_dark_mode):
        super().__init__(parent)
        self.title(title)
        self.result = None
        bg_color = "#252526" if is_dark_mode else "SystemButtonFace"
        fg_color = "#FF5555" if is_dark_mode else "red"
        self.configure(bg=bg_color)
        label = ttk.Label(self, text=message, background=bg_color, foreground=fg_color, font=("Consolas", 12))
        label.pack(padx=20, pady=20)
        button_frame = ttk.Frame(self, style="TFrame")
        button_frame.pack(pady=10)
        yes_button = ttk.Button(button_frame, text="Yes", command=self.on_yes, style="TButton")
        yes_button.pack(side="left", padx=10)
        no_button = ttk.Button(button_frame, text="No", command=self.on_no, style="TButton")
        no_button.pack(side="left", padx=10)
        self.transient(parent)
        self.update_idletasks()
        parent_x, parent_y = parent.winfo_x(), parent.winfo_y()
        parent_width, parent_height = parent.winfo_width(), parent.winfo_height()
        dialog_width, dialog_height = self.winfo_width(), self.winfo_height()
        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2
        self.geometry(f"+{x}+{y}")
        self.protocol("WM_DELETE_WINDOW", self.on_no)
        self.grab_set()
        self.wait_window()

    def on_yes(self):
        self.result = True
        self.destroy()

    def on_no(self):
        self.result = False
        self.destroy()

class MortarCalculatorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Arma Reforger Mortar Calculator")
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        width, height = 1015, 1180
        x = screen_width - width
        y = 0
        self.geometry(f"{width}x{height}+{x}+{y}")

        # Core Application State
        self.is_dark_mode = False
        
        self.state = StateManager()
        self.mortar_input_widgets = []
        self.mortar_colors = ["blue", "green", "purple", "orange"]

        self.style = ttk.Style(self)
        self.config_manager = ConfigManager()
        self.theme_manager = ThemeManager(self)
        self.dev_log = DevLog()
        
        self.setup_ui() # Setup UI first to create widgets
        
        self.on_faction_change() # Set initial ammo and charge based on default faction
        self.theme_manager.apply_theme() # Apply theme after UI is set up
        
        self.after(100, self.post_init_load)
        self.on_targeting_mode_change() # Set initial view

        # Setup worker thread and queues
        self.task_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.worker = threading.Thread(target=worker_thread, args=(self.task_queue, self.result_queue, self), daemon=True)
        self.worker.start()
 
        # Bind custom event for worker thread communication
        self.bind("<<CalculationFinished>>", self.on_calculation_finished)
 
        self.bind('<Control-Return>', lambda event: self.calculate_all())
        self.bind('<Control-n>', lambda event: self.new_mission())
        self.bind('<Control-l>', lambda event: self.load_file_smart())
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _get_float_or_default(self, tk_var, default_value=0.0):
        """Helper to safely get float from a Tkinter variable, defaulting if empty or invalid."""
        try:
            value = tk_var.get()
            if isinstance(value, str) and value.strip() == "":
                return default_value
            return float(value)
        except (ValueError, tk.TclError):
            return default_value

    def setup_ui(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)
        main_tab_frame = ttk.Frame(self.notebook, padding="10")
        self.trp_tab = ttk.Frame(self.notebook) # New TRP tab frame
        self.fire_mission_planner_tab = ttk.Frame(self.notebook)
        self.settings_tab = ttk.Frame(self.notebook)
        
        self.canvas = tk.Canvas(main_tab_frame)
        self.scrollbar = ttk.Scrollbar(main_tab_frame, orient="vertical", command=self.canvas.yview)
        self.main_tab = ttk.Frame(self.canvas)
        
        self.main_tab.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        
        main_tab_window = self.canvas.create_window((0, 0), window=self.main_tab, anchor="nw")

        def on_canvas_configure(event):
            self.canvas.itemconfig(main_tab_window, width=event.width)
        self.canvas.bind("<Configure>", on_canvas_configure)
        
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        def _on_global_mousewheel(event):
            # Check if the widget under the cursor is the map canvas or a child of it
            widget_under_cursor = self.winfo_containing(event.x_root, event.y_root)
            if widget_under_cursor != self.map_view_widget.graph_canvas and not isinstance(widget_under_cursor, ttk.Combobox):
                self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.bind_all("<MouseWheel>", _on_global_mousewheel)

        self.notebook.add(main_tab_frame, text="Main")
        self.notebook.add(self.trp_tab, text="TRP") # Add TRP tab
        self.notebook.add(self.fire_mission_planner_tab, text="Fire Mission Planner")
        self.notebook.add(self.settings_tab, text="Settings")

        self.setup_trp_tab() # Setup TRP tab first
        self.setup_main_tab()
        self.setup_results_widgets()
        self.setup_fire_mission_planner_tab()
        self.setup_settings_tab()
        self.mission_log = MissionLog(self.main_tab, self, self.config_manager)

    def post_init_load(self):
        """Load configs and populate UI after the main loop has started."""
        self.settings_view.refresh_map_list()
        map_list = self.settings_view.map_selection_combo['values']
        if "Zarichne.png" in map_list:
            self.state.selected_map_var.set("Zarichne.png")
        elif map_list:
            self.state.selected_map_var.set(map_list[0])
        self.settings_view.on_map_selected()

    def setup_main_tab(self):
        input_frame = ttk.Frame(self.main_tab)
        input_frame.pack(fill="both", expand=True)
        
        self.mortar_frame = ttk.LabelFrame(input_frame, text="1. Mortar Positions")
        self.mortar_frame.pack(fill="x", expand=True, pady=5)

        # --- Mortar Count ---
        mortar_count_frame = ttk.Frame(self.mortar_frame)
        mortar_count_frame.pack(side="top", fill="x", padx=5, pady=5)
        ttk.Label(mortar_count_frame, text="Number of Mortars:").grid(row=0, column=0, sticky="w")
        num_mortars_combo = ttk.Combobox(mortar_count_frame, textvariable=self.state.num_mortars_var, values=[1, 2, 3, 4], width=5, state="readonly")
        num_mortars_combo.grid(row=0, column=1, sticky="w", padx=5)
        num_mortars_combo.bind("<<ComboboxSelected>>", self.update_mortar_inputs)
        
        self.mortar_inputs_container = ttk.Frame(self.mortar_frame)
        self.mortar_inputs_container.pack(side="top", fill="x", expand=True)

        self.update_mortar_inputs()

        fire_mission_frame = ttk.LabelFrame(input_frame, text="2. Fire Mission")
        fire_mission_frame.pack(fill="x", expand=True, pady=5)

        # --- Right Frame for Ammo ---
        right_fm_frame = ttk.Frame(fire_mission_frame)
        right_fm_frame.pack(side="right", padx=20, pady=5, anchor="n")

        # --- Faction Selection ---
        faction_frame = ttk.Frame(right_fm_frame)
        faction_frame.pack(anchor="w", pady=(0,10))
        ttk.Label(faction_frame, text="Faction:").pack(side="left", anchor="w")
        nato_radio = ttk.Radiobutton(faction_frame, text="NATO", variable=self.state.faction_var, value="NATO", command=self.on_faction_change)
        nato_radio.pack(side="left", padx=5)
        ru_radio = ttk.Radiobutton(faction_frame, text="RU", variable=self.state.faction_var, value="RU", command=self.on_faction_change)
        ru_radio.pack(side="left")

        ttk.Label(right_fm_frame, text="Ammunition:").pack(anchor="w")
        self.ammo_type_combo = ttk.Combobox(right_fm_frame, textvariable=self.state.ammo_type_var, state="readonly")
        self.ammo_type_combo.pack(anchor="w")
        self.ammo_type_combo.bind("<<ComboboxSelected>>", self.update_charge_options)

        # --- Center Frame for Mission Type ---
        center_fm_frame = ttk.Frame(fire_mission_frame)
        center_fm_frame.pack(expand=True, pady=5)

        # --- Targeting Mode ---
        targeting_mode_frame = ttk.Frame(center_fm_frame)
        targeting_mode_frame.grid(row=0, column=2, sticky="ns", pady=2, padx=20)
        ttk.Label(targeting_mode_frame, text="Targeting Mode:").pack(anchor="w")
        ttk.Radiobutton(targeting_mode_frame, text="Polar (FO)", variable=self.state.targeting_mode_var, value="Polar", command=self.on_targeting_mode_change).pack(anchor="w")
        ttk.Radiobutton(targeting_mode_frame, text="Grid (TRP)", variable=self.state.targeting_mode_var, value="Grid", command=self.on_targeting_mode_change).pack(anchor="w")
        
        ttk.Label(center_fm_frame, text="Mission Type:").grid(row=0, column=0, sticky="ns", pady=2, rowspan=2)
        
        mission_type_grid = ttk.Frame(center_fm_frame)
        mission_type_grid.grid(row=0, column=1, sticky="w", padx=5, rowspan=2)

        mission_types = ["Regular", "Small Barrage", "Large Barrage", "Creeping Barrage"]
        ttk.Radiobutton(mission_type_grid, text=mission_types[0], variable=self.state.fire_mission_type_var, value=mission_types[0], command=self.on_mission_type_change).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(mission_type_grid, text=mission_types[3], variable=self.state.fire_mission_type_var, value=mission_types[3], command=self.on_mission_type_change).grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(mission_type_grid, text=mission_types[1], variable=self.state.fire_mission_type_var, value=mission_types[1], command=self.on_mission_type_change).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(mission_type_grid, text=mission_types[2], variable=self.state.fire_mission_type_var, value=mission_types[2], command=self.on_mission_type_change).grid(row=1, column=1, sticky="w")

        # --- Targeting Data Frame (Container for FO and TRP) ---
        targeting_data_frame = ttk.LabelFrame(input_frame, text="3. Targeting Data")
        targeting_data_frame.pack(fill="x", expand=True, pady=5)

        self.fo_frame = ttk.LabelFrame(targeting_data_frame, text="Forward Observer (FO) Data")
        # self.fo_frame is packed in on_targeting_mode_change

        ttk.Label(self.fo_frame, text="FO 10-Digit Grid:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        ttk.Entry(self.fo_frame, textvariable=self.state.fo_grid_var, width=12).grid(row=0, column=1, padx=5, pady=2)
        ttk.Label(self.fo_frame, text="FO Elevation (m):").grid(row=0, column=2, padx=5, pady=2, sticky="w")
        ttk.Entry(self.fo_frame, textvariable=self.state.fo_elev_var, width=7).grid(row=0, column=3, padx=5, pady=2)
        ttk.Label(self.fo_frame, text="FO ID:").grid(row=0, column=4, padx=5, pady=2, sticky="w")
        ttk.Entry(self.fo_frame, textvariable=self.state.fo_id_var, width=12).grid(row=0, column=5, padx=5, pady=2)
        ttk.Label(self.fo_frame, text="Azimuth to Target (Degrees):").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        ttk.Entry(self.fo_frame, textvariable=self.state.fo_azimuth_var, width=7).grid(row=1, column=1, padx=5, pady=2)
        ttk.Label(self.fo_frame, text="Distance to Target (m):").grid(row=1, column=2, padx=5, pady=2, sticky="w")
        ttk.Entry(self.fo_frame, textvariable=self.state.fo_dist_var, width=7).grid(row=1, column=3, padx=5, pady=2)
        ttk.Label(self.fo_frame, text="Elev. Change to Target (m):").grid(row=2, column=0, padx=5, pady=2, sticky="w")
        ttk.Entry(self.fo_frame, textvariable=self.state.fo_elev_diff_var, width=7).grid(row=2, column=1, padx=5, pady=2)
        
        self.creep_direction_label = ttk.Label(self.fo_frame, text="Creep Direction (Degrees):")
        self.creep_direction_label.grid(row=2, column=2, padx=5, pady=2, sticky="w")
        self.creep_direction_entry = ttk.Entry(self.fo_frame, textvariable=self.state.creep_direction_var, width=7)
        self.creep_direction_entry.grid(row=2, column=3, padx=5, pady=2)

        self.creep_spread_label = ttk.Label(self.fo_frame, text="Creep Spread (x):")
        self.creep_spread_label.grid(row=3, column=0, padx=5, pady=2, sticky="w")
        self.creep_spread_slider = ttk.Scale(self.fo_frame, from_=0.5, to=2.0, orient="horizontal", variable=self.state.creep_spread_var)
        self.creep_spread_slider.grid(row=3, column=1, padx=5, pady=2, sticky="ew")
        self.creep_spread_value_label = ttk.Label(self.fo_frame, textvariable=self.state.creep_spread_var)
        self.creep_spread_value_label.grid(row=3, column=2, padx=5, pady=2, sticky="w")

        self.trp_frame = ttk.LabelFrame(targeting_data_frame, text="Target Reference Point (TRP) Data")
        # self.trp_frame is packed in on_targeting_mode_change
        ttk.Label(self.trp_frame, text="Target 10-Digit Grid:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        ttk.Entry(self.trp_frame, textvariable=self.state.trp_grid_var, width=12).grid(row=0, column=1, padx=5, pady=2)
        ttk.Label(self.trp_frame, text="Target Elevation (m):").grid(row=0, column=2, padx=5, pady=2, sticky="w")
        ttk.Entry(self.trp_frame, textvariable=self.state.trp_elev_var, width=7).grid(row=0, column=3, padx=5, pady=2)
        
        self.load_trp_to_main_button = ttk.Button(self.trp_frame, text="Load TRP from TRP List", command=self.trp_view.load_valid_trp_to_main)
        self.load_trp_to_main_button.grid(row=1, column=0, columnspan=4, pady=5)

        corr_frame = ttk.LabelFrame(input_frame, text="4. Fire Mission Corrections (Optional)")
        corr_frame.pack(fill="x", expand=True, pady=5)
        ttk.Label(corr_frame, text="Left(-)/Right(+) (m):").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        ttk.Entry(corr_frame, textvariable=self.state.corr_lr_var, width=7).grid(row=0, column=1, padx=5, pady=2)
        ttk.Label(corr_frame, text="Add(+)/Drop(-) (m):").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        ttk.Entry(corr_frame, textvariable=self.state.corr_ad_var, width=7).grid(row=1, column=1, padx=5, pady=2)
        ttk.Label(corr_frame, text="Charge Used for Spotting:").grid(row=2, column=0, padx=5, pady=2, sticky="w")
        self.spotting_charge_combo = ttk.Combobox(corr_frame, textvariable=self.state.spotting_charge_var, state="readonly", width=5)
        self.spotting_charge_combo.grid(row=2, column=1, padx=5, pady=2)


        self.quick_fire_frame = ttk.LabelFrame(input_frame, text="Quick Fire Data")
        
        self.danger_close_label = ttk.Label(self.quick_fire_frame, text="DANGER CLOSE FIRE MISSION", style="DangerClose.TLabel")
        self.danger_close_label.grid(row=0, column=2, rowspan=3, padx=20)
        self.danger_close_label.grid_remove()
        

        self.quick_fire_frame.pack(fill="x", expand=True, pady=5)


    def setup_fire_mission_planner_tab(self):
        self.fire_mission_planner_view = FireMissionPlannerView(self.fire_mission_planner_tab, self)

    def setup_trp_tab(self):
        self.trp_view = TRPView(self.trp_tab, self)

    def setup_settings_tab(self):
        self.settings_view = SettingsView(self.settings_tab, self)

    def setup_results_widgets(self):
        results_frame = ttk.Frame(self.main_tab)
        results_frame.pack(fill="both", expand=True)
        left_frame = ttk.Frame(results_frame)
        left_frame.pack(side="left", fill="both", expand=True, padx=5)
        right_frame = ttk.Frame(results_frame)
        right_frame.pack(side="right", fill="both", expand=True, padx=5)

        action_frame = ttk.Frame(left_frame)
        action_frame.pack(pady=10, fill="x")
        action_frame.grid_columnconfigure(0, weight=1)
        ttk.Button(action_frame, text="Calculate Firing Solution", command=self.calculate_all).grid(row=0, column=0)

        target_details_frame = ttk.LabelFrame(left_frame, text="Calculated Target Details")
        target_details_frame.pack(fill="x", expand=True, pady=5)
        ttk.Label(target_details_frame, text="Target 10-Digit Grid:").grid(row=0, column=0, sticky="w", padx=5)
        ttk.Label(target_details_frame, textvariable=self.state.target_grid_10_var, font="SegoeUI 10 bold").grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(target_details_frame, text="Target Elevation:").grid(row=1, column=0, sticky="w", padx=5)
        ttk.Label(target_details_frame, textvariable=self.state.target_elev_var, font="SegoeUI 10 bold").grid(row=1, column=1, sticky="w", padx=5)
        azimuth_frame = ttk.Frame(target_details_frame, style="Highlight.TFrame")
        azimuth_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=2)
        inner_azimuth_frame = ttk.Frame(azimuth_frame, style="TFrame")
        inner_azimuth_frame.pack(fill="both", expand=True, padx=1, pady=1)
        inner_azimuth_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(inner_azimuth_frame, text="Mortar-Target Azimuth:", style="Highlight.TLabel").grid(row=0, column=0, sticky="w", padx=(5, 10))
        ttk.Label(inner_azimuth_frame, textvariable=self.state.mortar_to_target_azimuth_var, style="Highlight.Bold.TLabel").grid(row=0, column=1, sticky="w", padx=(0, 5))
        ttk.Label(target_details_frame, text="Mortar-Target Distance:").grid(row=3, column=0, sticky="w", padx=5)
        ttk.Label(target_details_frame, textvariable=self.state.mortar_to_target_dist_var, font="SegoeUI 10 bold").grid(row=3, column=1, sticky="w", padx=5)
        ttk.Label(target_details_frame, text="Mortar-Target Elev. Change:").grid(row=4, column=0, sticky="w", padx=5)
        ttk.Label(target_details_frame, textvariable=self.state.mortar_to_target_elev_diff_var, font="SegoeUI 10 bold").grid(row=4, column=1, sticky="w", padx=5)

        self.solution_frame = ttk.LabelFrame(left_frame, text="Final Firing Solution")
        self.solution_frame.pack(fill="both", expand=True, pady=5)
        
        self.map_view_widget = MapView(right_frame, self)
        self.map_view_widget.pack(fill="both", expand=True, pady=5)

        self.status_label = ttk.Label(self.solution_frame, textvariable=self.state.correction_status_var, font="SegoeUI 10 bold")
        self.status_label.grid(row=0, column=0, columnspan=3, pady=(0, 5))

        self.solution_notebook = ttk.Notebook(self.solution_frame)
        self.solution_notebook.grid(row=1, column=0, columnspan=3, sticky="nsew")
        self.solution_frame.grid_rowconfigure(1, weight=1)
        self.solution_frame.grid_columnconfigure(0, weight=1)

    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        if self.is_dark_mode:
            self.settings_view.theme_button.config(text="Toggle Light Mode")
            bg_color, fg_color, frame_bg, entry_bg, button_bg, border_color = "#1E1E1E", "#00FF00", "#252526", "#3C3C3C", "#3C3C3C", "#3C3C3C"
            self.style.theme_use('default')
            self.update_idletasks() # Ensure theme is fully applied before custom styles
            self.style.configure(".", background=bg_color, foreground=fg_color)
            self.style.configure("TFrame", background=bg_color)
            self.style.configure("TLabel", background=bg_color, foreground=fg_color, font=("Consolas", 10))
            self.style.configure("TLabelFrame", background=frame_bg, bordercolor=border_color, relief="solid")
            self.style.configure("TLabelFrame.Label", background=frame_bg, foreground=fg_color, font=("Consolas", 10, "bold"))
            self.style.configure("TButton", background=button_bg, foreground=fg_color, font=("Consolas", 10), borderwidth=1)
            self.style.map("TButton", background=[('active', '#6E6E6E')])
            self.style.configure("TCombobox", selectbackground=entry_bg, fieldbackground=entry_bg, background=button_bg, foreground=fg_color)
            self.style.map('TCombobox', fieldbackground=[('readonly', entry_bg)], selectbackground=[('readonly', entry_bg)], selectforeground=[('readonly', fg_color)])
            self.option_add('*TCombobox*Listbox.background', entry_bg)
            self.option_add('*TCombobox*Listbox.foreground', fg_color)
            self.option_add('*TCombobox*Listbox.selectBackground', button_bg)
            self.option_add('*TCombobox*Listbox.selectForeground', fg_color)
            self.style.configure("TEntry", fieldbackground=entry_bg, foreground=fg_color, insertcolor=fg_color)
            self.style.configure("Treeview", background=entry_bg, foreground=fg_color, fieldbackground=entry_bg)
            self.style.configure("Treeview.Heading", background=button_bg, foreground=fg_color)
            self.style.configure("TNotebook", background=bg_color, borderwidth=0)
            self.style.configure("TNotebook.Tab", background=frame_bg, foreground=fg_color, padding=[5, 2])
            self.style.map("TNotebook.Tab", background=[("selected", bg_color)], foreground=[("selected", fg_color)])
            self.style.configure("TCheckbutton", background=frame_bg, foreground=fg_color, font=("Consolas", 10))
            self.style.map("TCheckbutton", background=[('active', '#6E6E6E')], foreground=[('active', fg_color)])
            self.style.configure("Highlight.TFrame", background=bg_color, relief="solid", borderwidth=1, bordercolor="white")
            self.style.configure("Highlight.TLabel", background=bg_color, foreground=fg_color, font=("Consolas", 10))
            self.style.configure("Highlight.Bold.TLabel", background=bg_color, foreground=fg_color, font=("Consolas", 10, "bold"))
            self.style.configure("Highlight.BigBold.TLabel", background=bg_color, foreground=fg_color, font=("Consolas", 12, "bold"))
            self.style.configure("QuickFire.TLabel", background=frame_bg, foreground="red", font=("Consolas", 14, "bold"))
            self.style.configure("DangerClose.TLabel", background=frame_bg, foreground="red", font=("Consolas", 18, "bold"))
            self.configure(background=bg_color)
            self.map_view_widget.graph_canvas.config(bg=frame_bg)
            self.status_label.config(foreground="#FF5555")
            if hasattr(self.settings_view, 'admin_status_label') and self.state.admin_mode_enabled.get():
                self.settings_view.admin_status_label.config(foreground="#00FF00")
            if hasattr(self.settings_view, 'hidden_button_label'):
                self.settings_view.hidden_button_label.config(bg=bg_color)
            if hasattr(self, 'fire_mission_planner_view'):
                self.fire_mission_planner_view.apply_theme()
            if hasattr(self, 'trp_view'):
                self.trp_view.apply_theme()
        else:
            self.settings_view.theme_button.config(text="Toggle Dark Mode")
            self.style.theme_use('vista')
            self.update_idletasks() # Ensure theme is fully applied before custom styles
            self.configure(background="SystemButtonFace")
            self.map_view_widget.graph_canvas.config(bg="white")
            self.status_label.config(foreground="red")
            self.option_add('*TCombobox*Listbox.background', "white")
            self.option_add('*TCombobox*Listbox.foreground', "black")
            self.option_add('*TCombobox*Listbox.selectBackground', "blue")
            self.option_add('*TCombobox*Listbox.selectForeground', "white")
            if hasattr(self.settings_view, 'admin_status_label') and self.state.admin_mode_enabled.get():
                self.settings_view.admin_status_label.config(foreground="green")
            if hasattr(self.settings_view, 'hidden_button_label'):
                self.settings_view.hidden_button_label.config(bg=self.cget('bg'))
            if hasattr(self, 'fire_mission_planner_view'):
                self.fire_mission_planner_view.apply_theme()
            if hasattr(self, 'trp_view'):
                self.trp_view.apply_theme()

    def update_mortar_inputs(self, event=None):
        # Detach scrollbar to prevent visual glitches during update
        self.canvas.configure(yscrollcommand=None)

        # Clear all widgets from the frame for a clean slate
        # Clear only the container for mortar inputs, not the count selector
        # Store current mortar data before clearing
        # Store current mortar data, prioritizing locked fields
        preserved_locked_data = {}
        for i in range(len(self.state.mortar_input_vars)):
            mortar_vars = self.state.get_mortar_vars(i)
            if mortar_vars['locked'].get():
                preserved_locked_data[i] = {
                    "grid": mortar_vars['grid'].get(),
                    "elev": mortar_vars['elev'].get(),
                    "callsign": mortar_vars['callsign'].get(),
                    "locked": True
                }

        # Clear all widgets from the frame for a clean slate
        for widget in self.mortar_inputs_container.winfo_children():
            widget.destroy()
        self.state.clear_mortars()
        self.mortar_input_widgets.clear()

        num_mortars = self.state.num_mortars_var.get()
        
        # Add a vertical separator if there are two columns of guns
        if num_mortars > 1:
            row_span = 4 if num_mortars > 2 else 2
            sep = ttk.Separator(self.mortar_inputs_container, orient='vertical')
            sep.grid(row=0, column=4, rowspan=row_span, sticky='ns', padx=10)

        for i in range(num_mortars):
            self.state.add_mortar()
            mortar_vars = self.state.get_mortar_vars(i)

            # Populate with preserved locked data if available for this index
            if i in preserved_locked_data:
                data = preserved_locked_data[i]
                mortar_vars['grid'].set(data['grid'])
                mortar_vars['elev'].set(data['elev'])
                mortar_vars['callsign'].set(data['callsign'])
                mortar_vars['locked'].set(data['locked'])
            # Else, it will be initialized with default values from add_mortar()

            # Determine grid position (odd guns on left, even on right)
            row_base = (i // 2) * 2
            col_base = (i % 2) * 5

            # Create and place widgets
            ttk.Label(self.mortar_inputs_container, text=f"Gun {i+1} Grid:").grid(row=row_base, column=col_base, padx=5, pady=2, sticky="w")
            grid_entry = ttk.Entry(self.mortar_inputs_container, textvariable=mortar_vars['grid'], width=12)
            grid_entry.grid(row=row_base, column=col_base + 1, padx=5, pady=2)
            
            ttk.Label(self.mortar_inputs_container, text="Elev:").grid(row=row_base, column=col_base + 2, padx=5, pady=2, sticky="w")
            elev_entry = ttk.Entry(self.mortar_inputs_container, textvariable=mortar_vars['elev'], width=7)
            elev_entry.grid(row=row_base, column=col_base + 3, padx=5, pady=2)

            ttk.Label(self.mortar_inputs_container, text="Callsign:").grid(row=row_base + 1, column=col_base, padx=5, pady=2, sticky="w")
            callsign_entry = ttk.Entry(self.mortar_inputs_container, textvariable=mortar_vars['callsign'], width=12)
            callsign_entry.grid(row=row_base + 1, column=col_base + 1, padx=5, pady=2)

            lock_check = ttk.Checkbutton(self.mortar_inputs_container, text="Lock", variable=mortar_vars['locked'], command=lambda i=i: self.toggle_mortar_lock(i))
            lock_check.grid(row=row_base + 1, column=col_base + 2, padx=5, pady=2)

            self.mortar_input_widgets.append({"grid": grid_entry, "elev": elev_entry, "callsign": callsign_entry})
            self.toggle_mortar_lock(i)

        # Re-attach scrollbar and force UI update
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.update_idletasks()

    def toggle_mortar_lock(self, index):
        widgets = self.mortar_input_widgets[index]
        is_locked = self.state.get_mortar_vars(index)['locked'].get()
        state = "readonly" if is_locked else "normal"

        if is_locked:
            style_name = f"Locked.Gun{index}.TEntry"
            lock_color = self.mortar_colors[index]
            
            # Create a new style for the locked entry fields
            # The 'map' function is used to define appearance for specific states
            self.style.map(style_name,
                           foreground=[('readonly', 'white')],
                           fieldbackground=[('readonly', lock_color)])
            
            for widget in widgets.values():
                widget.configure(style=style_name)
        else:
            # Revert to the default style when unlocked
            for widget in widgets.values():
                widget.configure(style="TEntry")

        # Apply the readonly/normal state after the style has been set
        for widget in widgets.values():
            widget.config(state=state)

    def on_targeting_mode_change(self):
        """Shows or hides UI elements based on the selected targeting mode."""
        if self.state.targeting_mode_var.get() == "Polar":
            self.trp_frame.pack_forget()
            self.fo_frame.pack(fill="x", expand=True, padx=5, pady=5)
            self.load_trp_to_main_button.grid_remove() # Hide button in Polar mode
        else: # Grid
            self.fo_frame.pack_forget()
            self.trp_frame.pack(fill="x", expand=True, padx=5, pady=5)
            self.load_trp_to_main_button.grid() # Show button in Grid mode

    def on_faction_change(self):
        """Updates the ammunition dropdown based on the selected faction."""
        selected_faction = self.state.faction_var.get()
        ammo_list = list(BALLISTIC_DATA.get(selected_faction, {}).keys())
        self.ammo_type_combo['values'] = ammo_list
        if ammo_list:
            self.state.ammo_type_var.set(ammo_list[0])
        else:
            self.state.ammo_type_var.set("")
        self.update_charge_options()

    def update_charge_options(self, event=None):
        selected_faction = self.state.faction_var.get()
        selected_ammo = self.state.ammo_type_var.get()
        if selected_faction and selected_ammo:
            charges = list(BALLISTIC_DATA[selected_faction][selected_ammo].keys())
            self.spotting_charge_combo['values'] = charges
            if charges:
                self.spotting_charge_combo.current(0)

    def on_map_right_click(self, event):
        if not self.state.admin_mode_enabled.get():
            return
        map_e, map_n = self.map_view_widget.canvas_to_map_coords(event.x, event.y)
        if map_e is not None and map_n is not None:
            self.state.admin_target_pin = (map_e, map_n)
            self.state.target_grid_10_var.set(f"{int(round(map_e)):05d} {int(round(map_n)):05d}")
            target_elev = self.state.fo_elev_var.get() + self.state.fo_elev_diff_var.get()
            self.state.target_elev_var.set(f"{target_elev:.1f} m")
            self.state.mortar_to_target_azimuth_var.set("-- MIL")
            self.state.mortar_to_target_dist_var.set("-- m")
            self.state.mortar_to_target_elev_diff_var.set("-- m")
            self.clear_solution()
            self.state.fo_grid_var.set("--- ADMIN ---")
            self.state.fo_azimuth_var.set(0)
            self.state.fo_dist_var.set(0)
            self.map_view_widget.plot_positions()

    def calculate_all(self, trp_data=None):
        """Queues a calculation task for the worker thread.
        If trp_data is provided, it's a single TRP from a list calculation."""
        try:
            if trp_data is None: # Regular single calculation from Main tab
                self.state.correction_status_var.set("Calculating...")
                if hasattr(self, 'flash_dc_job'):
                    self.after_cancel(self.flash_dc_job)
                    self.danger_close_label.grid_remove()

            mortars_data = []
            for i in range(self.state.num_mortars_var.get()):
                mortar_vars = self.state.get_mortar_vars(i)
                mortars_data.append({
                    "grid": mortar_vars['grid'].get(),
                    "elev": self._get_float_or_default(mortar_vars['elev']),
                    "callsign": mortar_vars['callsign'].get()
                })

            task = {
                'mission_type': self.state.fire_mission_type_var.get(),
                'targeting_mode': self.state.targeting_mode_var.get(),
                'faction': self.state.faction_var.get(),
                'ammo': self.state.ammo_type_var.get(),
                'creep_direction': self._get_float_or_default(self.state.creep_direction_var),
                'creep_spread': self._get_float_or_default(self.state.creep_spread_var, 1.0),
                'fo_grid_str': self.state.fo_grid_var.get(),
                'fo_elev': self._get_float_or_default(self.state.fo_elev_var),
                'fo_azimuth_deg': self._get_float_or_default(self.state.fo_azimuth_var),
                'fo_dist': self._get_float_or_default(self.state.fo_dist_var),
                'fo_elev_diff': self._get_float_or_default(self.state.fo_elev_diff_var),
                'corr_lr': self._get_float_or_default(self.state.corr_lr_var),
                'corr_ad': self._get_float_or_default(self.state.corr_ad_var),
                'mortars': mortars_data,
                'target_grid_str': self.state.trp_grid_var.get() if trp_data is None else trp_data['grid'],
                'target_elev': self._get_float_or_default(self.state.trp_elev_var) if trp_data is None else self._get_float_or_default(tk.DoubleVar(value=trp_data['elev'])),
                'is_trp_list_calc': trp_data is not None, # Flag to indicate if it's part of a TRP list calculation
                'trp_name': trp_data['name'] if trp_data is not None else None
            }
            self.task_queue.put(task)
        except Exception as e:
            self.handle_calculation_error(e)

    def on_calculation_finished(self, event=None):
        """Handles the custom event triggered by the worker thread."""
        try:
            result = self.result_queue.get_nowait()
            if isinstance(result, Exception):
                self.handle_calculation_error(result)
            else:
                if result.get('is_trp_list_calc', False):
                    self.process_trp_list_calculation_result(result)
                else:
                    self.process_and_update_ui(result)
        except queue.Empty:
            pass  # Should not happen if event is triggered correctly

    def calculate_trps_from_list(self):
        """Initiates calculation for all TRPs in the list."""
        trps_to_calculate = [
            {
                "grid": trp_vars['grid'].get(),
                "elev": trp_vars['elev'].get(),
                "name": trp_vars['name'].get()
            }
            for trp_vars in self.state.trp_input_vars # Corrected from self.app.state
        ]

        if not trps_to_calculate:
            messagebox.showinfo("No TRPs", "No TRPs added to calculate.")
            return

        # Clear the mission log in memory without saving to disk
        self.mission_log.clear_log(save_to_disk=False)
 
        self.calculated_trp_results = [] # Store results for all TRPs
        self.current_trp_calc_index = 0
        self.total_trps_to_calc = len(trps_to_calculate)
        self.trp_list_calc_in_progress = True

        # Automatically switch to Grid (TRP) targeting mode on the main tab
        self.state.targeting_mode_var.set("Grid")
        self.on_targeting_mode_change()
        self.notebook.select(0) # Switch to Main tab
 
        # Start the first TRP calculation
        self.state.correction_status_var.set(f"Calculating TRP 1 of {self.total_trps_to_calc}...")
        self.calculate_all(trp_data=trps_to_calculate[0])
 
    def process_trp_list_calculation_result(self, result):
        """Processes a single TRP calculation result from the list."""
        self.calculated_trp_results.append(result)
        
        # Update the status of the corresponding TRP in state_manager
        if self.current_trp_calc_index < len(self.state.trp_input_vars):
            current_trp_vars = self.state.get_trp_vars(self.current_trp_calc_index)
            # Check if there's at least one valid solution among the results
            has_valid_solution = any(not sol.get('error') for sol in result.get('solutions', []))
            
            if has_valid_solution:
                current_trp_vars['status'].set("Solution Found")
            elif result.get('error'):
                current_trp_vars['status'].set(f"Error: {result['error']}")
            else:
                # If no valid solutions and no overall error, it means no solution was found for any mortar
                current_trp_vars['status'].set("No Solution")
            self.trp_view.refresh_trp_list() # Refresh TRP list to show status

        self.current_trp_calc_index += 1
 
        if self.current_trp_calc_index < self.total_trps_to_calc:
            # Continue with the next TRP
            next_trp_data = self.state.trp_input_vars[self.current_trp_calc_index]
            # Only update status bar, do not switch tabs or update main UI during batch calculation
            self.state.correction_status_var.set(f"Calculating TRP {self.current_trp_calc_index + 1} of {self.total_trps_to_calc}...")
            self.calculate_all(trp_data={
                "grid": next_trp_data['grid'].get(),
                "elev": next_trp_data['elev'].get(),
                "name": next_trp_data['name'].get()
            })
        else:
            # All TRPs calculated, process all results
            self.trp_list_calc_in_progress = False
            self.state.correction_status_var.set("All TRPs Calculated.")
            self.display_all_trp_results()

    def display_all_trp_results(self):
        """Displays the results of all TRP calculations."""
        # Clear previous solution display (only once at the end if needed)
        # self._clear_solution_ui() # Removed as per user feedback
        # self.clear_solution() # Removed as per user feedback

        valid_solutions_count = 0
        # Clear previous solution display on main tab
        # self._clear_solution_ui() # Removed as per user feedback
        # self.clear_solution() # Removed as per user feedback

        # Iterate through all calculated TRP results
        for result in self.calculated_trp_results:
            trp_name = result.get('trp_name', 'Unknown TRP')
            
            # Only process and log TRPs that have valid solutions
            if result.get('solutions') and not result.get('error'):
                valid_solutions_count += 1
                # The 'solutions' list now contains per-mortar results.
                # For logging, we need to aggregate or pick one representative.
                # The user wants to log "green ones" as if they were regular missions.
                # So, we'll create a log entry for each *valid* mortar solution within this TRP.
                
                for sol in result['solutions']:
                    if not sol.get('error'): # Only log if this specific mortar has a solution
                        # Do NOT update main UI with individual solutions during batch calculation
                        # self.state.last_solutions = [sol] # Removed as per user feedback
                        # self._update_target_details(sol) # Removed as per user feedback
                        # self.state.last_coords['mortars'] = [sol.get('mortar', {}).get('coords', (0,0))] # Removed as per user feedback
                        # self._create_solution_tabs([sol]) # Removed as per user feedback
                        
                        # Construct a full mission data dictionary for logging as a regular entry
                        mission_data_for_log = {
                            "target_name": trp_name,
                            "num_mortars": self.state.num_mortars_var.get(),
                            "fire_mission_type": self.state.fire_mission_type_var.get(),
                            "targeting_mode": "Grid", # Always "Grid" for TRP calculations
                            "fo_grid": self.state.fo_grid_var.get(),
                            "fo_elev": self.state.fo_elev_var.get(),
                            "fo_id": self.state.fo_id_var.get(),
                            "fo_azimuth_deg": self.state.fo_azimuth_var.get(),
                            "fo_dist": self.state.fo_dist_var.get(),
                            "fo_elev_diff": self.state.fo_elev_diff_var.get(),
                            "corr_lr": self.state.corr_lr_var.get(),
                            "corr_ad": self.state.corr_ad_var.get(),
                            "spotting_charge": self.state.spotting_charge_var.get(),
                            "faction": self.state.faction_var.get(),
                            "ammo": self.state.ammo_type_var.get(),
                            "calculated_target_grid": result.get('original_trp_grid', "00000 00000"),
                            "mortar_to_target_azimuth": f"{sol['azimuth']:.0f} MIL",
                            "mortar_to_target_dist": f"{sol['distance']:.0f} m",
                            "target_grid_str": trp_name, # Use TRP name as target_grid_str for consistency
                            "target_elev": result.get('original_trp_elev', 0.0),
                            "original_trp_grid": result.get('original_trp_grid', None), # Log original TRP grid
                            "original_trp_elev": result.get('original_trp_elev', None) # Log original TRP elevation
                        }
                        self.mission_log.log_mission_data_directly(mission_data_for_log)
            # No else block here, as invalid TRPs are only shown in the TRP tab's status column

        if valid_solutions_count > 0:
            messagebox.showinfo("TRP Calculation Results",
                                f"Calculated {valid_solutions_count} valid TRPs. "
                                f"Valid results logged to mission log.")
        else:
            messagebox.showinfo("TRP Calculation Results", "No valid TRPs were calculated.")

        # Update map only once at the end with all valid TRPs
        # Collect all valid TRP coordinates for plotting
        all_valid_trp_coords = []
        for result in self.calculated_trp_results:
            if result.get('solutions') and not result.get('error'):
                for sol in result['solutions']:
                    if not sol.get('error'):
                        all_valid_trp_coords.append(sol['target_coords'][:2]) # Only easting and northing
        
        # Update last_coords for map plotting
        self.state.last_coords['mortars'] = [] # Clear mortars for this plot
        self.state.last_coords['fo_e'] = None # Clear FO for this plot
        self.state.last_coords['fo_n'] = None # Clear FO for this plot
        self.state.last_coords['target_e'] = None # Clear single target for this plot
        self.state.last_coords['target_n'] = None # Clear single target for this plot
        
        # Add all valid TRP targets to last_coords for plotting
        self.state.last_coords['trp_targets'] = all_valid_trp_coords

        self.map_view_widget.auto_zoom_to_pins()
        self.map_view_widget.plot_positions()

    def confirm_danger_close(self):
        self.status_label.config(text="DANGER CLOSE ARE YOU SURE?", foreground="red")
        self.flash_danger_warning()
        dialog = CustomDialog(self, "DANGER CLOSE", "The target is dangerously close to the FO.\nAre you sure you want to proceed?", self.is_dark_mode)

        if hasattr(self, 'flash_job'):
            self.after_cancel(self.flash_job)
        self.status_label.config(text="")

        return dialog.result

    def flash_danger_warning(self):
        current_color = self.status_label.cget("foreground")
        next_color = "white" if current_color == "red" else "red"
        self.status_label.config(foreground=next_color)
        self.flash_job = self.after(353, self.flash_danger_warning)

    def flash_danger_close_label(self):
        if self.danger_close_label.winfo_viewable():
            self.danger_close_label.grid_remove()
        else:
            self.danger_close_label.grid(row=0, column=2, rowspan=3, padx=20)
        self.flash_dc_job = self.after(353, self.flash_danger_close_label)

    def process_and_update_ui(self, worker_result):
        """Processes the raw solutions from the worker and updates the UI."""
        try:
            # worker_result is now a dictionary: {'is_trp_list_calc': ..., 'trp_name': ..., 'solutions': [...]}
            solutions_from_worker = worker_result.get('solutions', [])
            
            fo_grid_str = self.state.fo_grid_var.get()
            fo_easting, fo_northing = parse_grid(fo_grid_str)
 
            processed_solutions = []
            # Iterate over the actual list of per-mortar results from the worker
            for sol in solutions_from_worker:
                # Each 'sol' now contains 'mortar', 'target_coords', 'least_tof', 'most_tof', 'error'
                if sol.get('error'):
                    # If there's an error for this mortar, just pass it through
                    processed_solutions.append(sol)
                    continue
                
                # Otherwise, process the valid solution
                mortar_e, mortar_n = sol['mortar']['coords']
                target_e, target_n, target_elev = sol['target_coords']
                
                # Azimuth, distance, elev_diff are now calculated in worker.py
                # So, just append the solution as is, it already has these keys
                processed_solutions.append(sol)
 
            self.state.last_solutions = processed_solutions
            self.update_ui_with_solution(processed_solutions)
            self.state.correction_status_var.set("")
        except Exception as e:
            self.handle_calculation_error(e)


    def _clear_solution_ui(self):
        """Clears the solution notebook and quick fire frames."""
        for tab in self.solution_notebook.tabs():
            self.solution_notebook.forget(tab)
        for widget in self.quick_fire_frame.winfo_children():
            widget.destroy()

    def _update_target_details(self, solution):
        """Updates the main target detail labels."""
        if not isinstance(solution, dict):
            print(f"Debug: _update_target_details received non-dict solution: {solution}")
            self.state.target_grid_10_var.set("----- -----")
            self.state.target_elev_var.set("-- m")
            self.state.mortar_to_target_azimuth_var.set("-- MIL")
            self.state.mortar_to_target_dist_var.set("-- m")
            self.state.mortar_to_target_elev_diff_var.set("-- m")
            return

        # This method is called inside a loop, so we only set the FO and target once.
        # The mortar coords are collected in update_ui_with_solution.
        # The FO coordinates are part of the overall state, not individual solutions
        # Get them from self.state directly
        fo_easting, fo_northing = parse_grid(self.state.fo_grid_var.get())

        if 'fo_e' not in self.state.last_coords:
            self.state.last_coords = {
                'mortars': [],
                'fo_e': fo_easting, 'fo_n': fo_northing,
                'target_e': solution.get('target_coords', [0,0,0])[0], 'target_n': solution.get('target_coords', [0,0,0])[1]
            }
        self.state.target_grid_10_var.set(f"{int(round(solution.get('target_coords', [0,0,0])[0])):.0f} {int(round(solution.get('target_coords', [0,0,0])[1])):.0f}")
        self.state.target_elev_var.set(f"{solution.get('target_elev', 0.0):.1f} m")
        self.state.mortar_to_target_azimuth_var.set(f"{solution.get('azimuth', 0.0):.0f} MIL")
        self.state.mortar_to_target_dist_var.set(f"{solution.get('distance', 0.0):.0f} m")
        self.state.mortar_to_target_elev_diff_var.set(f"{solution.get('elev_diff', 0.0):.1f} m")

    def _populate_solution_tab(self, tab_frame, sol, tab_color, gun_index):
        """Populates a single tab in the solution notebook with firing data,
        displaying error if no solution found for this mortar."""
        if not isinstance(sol, dict):
            print(f"Debug: _populate_solution_tab received non-dict solution: {sol}")
            ttk.Label(tab_frame, text="Error: Invalid Solution Data", foreground="red").pack(pady=10)
            return
        
        # Create unique styles for the labels within this tab
        label_style = f"Gun{gun_index}.TLabel"
        bold_label_style = f"Gun{gun_index}.Bold.TLabel"
        
        self.style.configure(label_style, background=tab_color, foreground="white", font=("Consolas", 10))
        self.style.configure(bold_label_style, background=tab_color, foreground="white", font=("Consolas", 10, "bold"))

        if sol.get('error'):
            ttk.Label(tab_frame, text=f"Error: {sol['error']}", foreground="red", wraplength=250).pack(pady=10)
            return
 
        ttk.Label(tab_frame, text="Least Time of Flight", style=bold_label_style).grid(row=0, column=1, padx=5)
        ttk.Label(tab_frame, text="Most Time of Flight", style=bold_label_style).grid(row=0, column=2, padx=5)
        
        ttk.Label(tab_frame, text="Charge (Rings):", style=label_style).grid(row=1, column=0, sticky="w", padx=5)
        ttk.Label(tab_frame, text=f"{sol.get('least_tof', {}).get('charge', '--')}", style=bold_label_style).grid(row=1, column=1, padx=5)
        ttk.Label(tab_frame, text=f"{sol.get('most_tof', {}).get('charge', '--')}", style=bold_label_style).grid(row=1, column=2, padx=5)
 
        # The elevation frame has its own highlighting, so we don't apply the tab color here.
        elevation_frame = ttk.Frame(tab_frame, style="Highlight.TFrame")
        elevation_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=2)
        inner_elevation_frame = ttk.Frame(elevation_frame, style="TFrame")
        inner_elevation_frame.pack(fill="both", expand=True, padx=1, pady=1)
        inner_elevation_frame.grid_columnconfigure(1, weight=1)
        inner_elevation_frame.grid_columnconfigure(2, weight=1)
        ttk.Label(inner_elevation_frame, text="Corrected Elevation:", style="Highlight.TLabel").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Label(inner_elevation_frame, text=f"{sol.get('least_tof', {}).get('elev', 0.0):.0f} MIL", style="Highlight.BigBold.TLabel").grid(row=0, column=1)
        ttk.Label(inner_elevation_frame, text=f"{sol.get('most_tof', {}).get('elev', 0.0):.0f} MIL", style="Highlight.BigBold.TLabel").grid(row=0, column=2)
 
        ttk.Label(tab_frame, text="Time of Flight:", style=label_style).grid(row=3, column=0, sticky="w", padx=5)
        ttk.Label(tab_frame, text=f"{sol.get('least_tof', {}).get('tof', 0.0):.1f} sec", style=bold_label_style).grid(row=3, column=1, padx=5)
        ttk.Label(tab_frame, text=f"{sol.get('most_tof', {}).get('tof', 0.0):.1f} sec", style=bold_label_style).grid(row=3, column=2, padx=5)
 
        ttk.Label(tab_frame, text="Dispersion Radius:", style=label_style).grid(row=4, column=0, sticky="w", padx=5)
        ttk.Label(tab_frame, text=f"{sol.get('least_tof', {}).get('dispersion', 0.0)} m", style=bold_label_style).grid(row=4, column=1, padx=5)
        ttk.Label(tab_frame, text=f"{sol.get('most_tof', {}).get('dispersion', 0.0)} m", style=bold_label_style).grid(row=4, column=2, padx=5)

    def _populate_quick_fire_data(self, sol, gun_index):
        """Populates the quick fire data frame for a single gun,
        displaying error if no solution found for this mortar."""
        if not isinstance(sol, dict):
            print(f"Debug: _populate_quick_fire_data received non-dict solution: {sol}")
            return

        gun_frame = ttk.LabelFrame(self.quick_fire_frame, text=f"Gun {gun_index + 1}")
        gun_frame.grid(row=0, column=gun_index, padx=5, pady=2, sticky="ns")
        
        if sol.get('error'):
            ttk.Label(gun_frame, text=f"Error: {sol['error']}", foreground="red", wraplength=100).pack(pady=5)
            # Clear quick fire variables for this gun if there's an error
            self.state.quick_azimuth_var.set("---- MIL")
            self.state.quick_least_tof_elev_var.set("C-: ---- MIL")
            self.state.quick_most_tof_elev_var.set("C-: ---- MIL")
            return

        ttk.Label(gun_frame, text="Azimuth:").pack(anchor="w")
        ttk.Label(gun_frame, text=f"{sol.get('azimuth', 0.0):.0f} MIL", style="QuickFire.TLabel").pack(anchor="w")
        ttk.Label(gun_frame, text="Least ToF Elev:").pack(anchor="w")
        ttk.Label(gun_frame, text=f"C-{sol.get('least_tof', {}).get('charge', '--')}: {sol.get('least_tof', {}).get('elev', 0.0):.0f} MIL", style="QuickFire.TLabel").pack(anchor="w")
        ttk.Label(gun_frame, text="Most ToF Elev:").pack(anchor="w")
        ttk.Label(gun_frame, text=f"C-{sol.get('most_tof', {}).get('charge', '--')}: {sol.get('most_tof', {}).get('elev', 0.0):.0f} MIL", style="QuickFire.TLabel").pack(anchor="w")

    def _create_solution_tabs(self, mortar_results):
        """Creates and populates the solution tabs and quick fire data for each mortar."""
        num_mortars = self.state.num_mortars_var.get()
        mission_type = self.state.fire_mission_type_var.get()
 
        for i, sol in enumerate(mortar_results): # Iterate through per-mortar results
            tab_title = f"Gun {i + 1}"
            if num_mortars == 1 and mission_type == "Regular":
                tab_title = "Firing Solution"
            
            # Create a unique style for the tab's frame
            frame_style_name = f"Gun{i}.TFrame"
            self.style.configure(frame_style_name, background=self.mortar_colors[i])
 
            tab_frame = ttk.Frame(self.solution_notebook, style=frame_style_name)
            self.solution_notebook.add(tab_frame, text=tab_title)
            
            self._populate_solution_tab(tab_frame, sol, self.mortar_colors[i], i)
            self._populate_quick_fire_data(sol, i)

    def update_ui_with_solution(self, solutions):
        """Updates the entire UI with the calculated firing solutions."""
        self._clear_solution_ui()

        if not solutions:
            self.clear_solution()
            return

        self.state.last_coords = {} # Clear previous coordinates
        
        # Filter for valid solutions before updating target details and mortar coords
        valid_solutions_for_display = [s for s in solutions if not s.get('error')]
        
        if valid_solutions_for_display:
            self._update_target_details(valid_solutions_for_display[0]) # Set FO and Target from first valid solution
            self.state.last_coords['mortars'] = [s.get('mortar', {}).get('coords', (0,0)) for s in valid_solutions_for_display] # Collect valid mortar coords
        else:
            # If no valid solutions, clear target details and mortar coords
            self._update_target_details({}) # Pass empty dict to clear
            self.state.last_coords['mortars'] = []
 
        self._create_solution_tabs(solutions) # Pass all solutions (including errors) to create tabs

        self.map_view_widget.auto_zoom_to_pins()
        self.map_view_widget.plot_positions()


    def handle_calculation_error(self, e):
        self.clear_solution(clear_error=True) # Clear previous solution before showing error
        self.state.correction_status_var.set(f"Error: {e}")
        if self.state.dev_log_enabled.get():
            self.dev_log.write_log(e)
        self.state.quick_azimuth_var.set("---- MIL")
        self.state.quick_least_tof_elev_var.set("C-: ---- MIL")
        self.state.quick_most_tof_elev_var.set("C-: ---- MIL")

    def clear_solution(self, clear_error=True):
        if clear_error:
            self.state.least_tof_charge_var.set("--")
            self.state.least_tof_elev_var.set("-- MIL")
        self.state.least_tof_tof_var.set("-- sec")
        self.state.least_tof_disp_var.set("-- m")
        self.state.most_tof_charge_var.set("--")
        self.state.most_tof_elev_var.set("-- MIL")
        self.state.most_tof_tof_var.set("-- sec")
        self.state.most_tof_disp_var.set("-- m")
        self.state.correction_status_var.set("")
        self.state.quick_azimuth_var.set("---- MIL")
        self.state.quick_least_tof_elev_var.set("C-: ---- MIL")
        self.state.quick_most_tof_elev_var.set("C-: ---- MIL")

    def get_current_mission_data_for_log(self):
        if self.state.targeting_mode_var.get() == "Grid":
            calculated_target_grid = self.state.trp_grid_var.get()
        else:
            try:
                target_easting, target_northing = calculate_target_coords(self.state.fo_grid_var.get(), self.state.fo_azimuth_var.get(), self.state.fo_dist_var.get(), self.state.fo_elev_diff_var.get(), self.state.corr_lr_var.get(), self.state.corr_ad_var.get())
                calculated_target_grid = f"{int(round(target_easting)):05d} {int(round(target_northing)):05d}"
            except Exception:
                calculated_target_grid = "Calculation Error"
        return {
            "target_name": self.mission_log.target_name_var.get(),
            "mortars": [
                {
                    "grid": self.state.get_mortar_vars(i)['grid'].get(),
                    "elev": self.state.get_mortar_vars(i)['elev'].get(),
                    "callsign": self.state.get_mortar_vars(i)['callsign'].get(),
                    "locked": self.state.get_mortar_vars(i)['locked'].get()
                } for i in range(self.state.num_mortars_var.get())
            ],
            "num_mortars": self.state.num_mortars_var.get(),
            "fire_mission_type": self.state.fire_mission_type_var.get(),
            "targeting_mode": self.state.targeting_mode_var.get(),
            "fo_grid": self.state.fo_grid_var.get(),
            "fo_elev": self.state.fo_elev_var.get(),
            "fo_id": self.state.fo_id_var.get(),
            "fo_azimuth_deg": self.state.fo_azimuth_var.get(),
            "fo_dist": self.state.fo_dist_var.get(),
            "fo_elev_diff": self.state.fo_elev_diff_var.get(),
            "corr_lr": self.state.corr_lr_var.get(),
            "corr_ad": self.state.corr_ad_var.get(),
            "spotting_charge": self.state.spotting_charge_var.get(),
            "faction": self.state.faction_var.get(),
            "ammo": self.state.ammo_type_var.get(),
            "calculated_target_grid": calculated_target_grid,
            "mortar_to_target_azimuth": self.state.mortar_to_target_azimuth_var.get(),
            "mortar_to_target_dist": self.state.mortar_to_target_dist_var.get(),
            "target_grid_str": self.state.trp_grid_var.get(),
            "target_elev": self.state.trp_elev_var.get()
        }

    def load_mission_data_from_log(self, mission_data):
        self.state.loaded_target_name.set(mission_data.get("target_name", "Target"))
        self.mission_log.target_name_var.set(mission_data.get("target_name", "Target"))
        
        loaded_mortars = []
        for mortar_data in mission_data.get("mortars", []):
            if mortar_data.get("grid", "") != "0000000000":
                loaded_mortars.append(mortar_data)

        # Store current locked state and values before updating num_mortars and calling update_mortar_inputs
        # This is crucial to prevent locked fields from being overwritten by loaded mission data
        current_locked_mortar_data = {}
        for i in range(len(self.state.mortar_input_vars)):
            mortar_vars = self.state.get_mortar_vars(i)
            if mortar_vars['locked'].get():
                current_locked_mortar_data[i] = {
                    "grid": mortar_vars['grid'].get(),
                    "elev": mortar_vars['elev'].get(),
                    "callsign": mortar_vars['callsign'].get(),
                    "locked": True
                }

        self.state.num_mortars_var.set(len(loaded_mortars) if loaded_mortars else 1)
        self.update_mortar_inputs() # This will clear existing and add new based on num_mortars_var, preserving locked data from current_locked_mortar_data

        for i, mortar_data in enumerate(loaded_mortars):
            if i < self.state.num_mortars_var.get(): # Ensure we don't go out of bounds
                mortar_vars = self.state.get_mortar_vars(i)
                
                # If this mortar was previously locked, do NOT overwrite its grid and elev
                if i in current_locked_mortar_data and current_locked_mortar_data[i]['locked']:
                    # Preserve grid and elev from the locked state
                    mortar_vars['grid'].set(current_locked_mortar_data[i]['grid'])
                    mortar_vars['elev'].set(self._get_float_or_default(tk.DoubleVar(value=current_locked_mortar_data[i]['elev'])))
                    mortar_vars['callsign'].set(current_locked_mortar_data[i]['callsign'])
                    mortar_vars['locked'].set(True) # Ensure it remains locked
                else:
                    # Otherwise, load data from the mission
                    mortar_vars['grid'].set(mortar_data.get("grid", ""))
                    mortar_vars['elev'].set(self._get_float_or_default(tk.DoubleVar(value=mortar_data.get("elev", 0))))
                    mortar_vars['callsign'].set(mortar_data.get("callsign", ""))
                    mortar_vars['locked'].set(mortar_data.get("locked", False))
                
                self.toggle_mortar_lock(i) # Apply lock state to UI

        self.state.fire_mission_type_var.set("Regular") # Default to Regular on load
        self.state.targeting_mode_var.set(mission_data.get("targeting_mode", "Polar"))
        self.on_targeting_mode_change()
        self.state.fo_grid_var.set(mission_data.get("fo_grid", ""))
        self.state.fo_elev_var.set(self._get_float_or_default(tk.DoubleVar(value=mission_data.get("fo_elev", 0))))
        self.state.fo_id_var.set(mission_data.get("fo_id", ""))
        self.state.fo_azimuth_var.set(self._get_float_or_default(tk.DoubleVar(value=mission_data.get("fo_azimuth_deg", 0))))
        self.state.fo_dist_var.set(self._get_float_or_default(tk.DoubleVar(value=mission_data.get("fo_dist", 0))))
        self.state.fo_elev_diff_var.set(self._get_float_or_default(tk.DoubleVar(value=mission_data.get("fo_elev_diff", 0))))
        self.state.corr_lr_var.set(self._get_float_or_default(tk.DoubleVar(value=mission_data.get("corr_lr", 0))))
        self.state.corr_ad_var.set(self._get_float_or_default(tk.DoubleVar(value=mission_data.get("corr_ad", 0))))
        self.state.faction_var.set(mission_data.get("faction", "NATO"))
        self.on_faction_change()
        self.state.ammo_type_var.set(mission_data.get("ammo", ""))
        self.update_charge_options()
        self.state.spotting_charge_var.set(mission_data.get("spotting_charge", 0))
        # Always set trp_grid_var and trp_elev_var from the calculated target data
        # This ensures that the Main tab's TRP fields reflect the loaded mission's target
        self.state.trp_grid_var.set(mission_data.get("calculated_target_grid", "0000000000"))
        self.state.trp_elev_var.set(mission_data.get("target_elev", 100))
        
        self.clear_solution()
        self.state.last_solutions = []
        self.state.last_coords = {}

        # Plot mortar and target positions without calculating a solution
        try:
            mortars = []
            for i in range(self.state.num_mortars_var.get()):
                mortar_vars = self.state.get_mortar_vars(i)
                grid = mortar_vars['grid'].get()
                try:
                    coords = parse_grid(grid)
                except ValueError as e:
                    # If 8-digit grid, ask user to convert
                    if "8 or 10 digits" in str(e) and len(grid) == 8:
                        if messagebox.askyesno("Convert Grid?", f"The mortar grid '{grid}' is 8 digits. Would you like to convert it to 10 digits by appending '00' to Easting and Northing?"):
                            easting = int(grid[:4]) * 10
                            northing = int(grid[4:]) * 10
                            coords = (easting, northing)
                            mortar_vars['grid'].set(f"{easting:05d}{northing:05d}") # Update the Tkinter variable
                        else:
                            raise e # User declined conversion, re-raise original error
                    else:
                        raise e # Not an 8-digit grid error, re-raise
                mortars.append({"coords": coords})
            
            fo_e, fo_n = parse_grid(self.state.fo_grid_var.get())
            target_e, target_n = calculate_target_coords(self.state.fo_grid_var.get(), self.state.fo_azimuth_var.get(), self.state.fo_dist_var.get(), self.state.fo_elev_diff_var.get(), 0, 0)

            self.state.last_coords = {
                'mortars': [m['coords'] for m in mortars],
                'fo_e': fo_e, 'fo_n': fo_n,
                'target_e': target_e, 'target_n': target_n
            }
        except Exception:
            self.state.last_coords = {} # Clear if there's an error parsing

        self.map_view_widget.plot_positions()

    def on_mission_type_change(self):
        is_creeping = self.state.fire_mission_type_var.get() == "Creeping Barrage"
        
        if is_creeping:
            self.creep_direction_label.grid()
            self.creep_direction_entry.grid()
            self.creep_spread_label.grid()
            self.creep_spread_slider.grid()
            self.creep_spread_value_label.grid()
        else:
            self.creep_direction_label.grid_remove()
            self.creep_direction_entry.grid_remove()
            self.creep_spread_label.grid_remove()
            self.creep_spread_slider.grid_remove()
            self.creep_spread_value_label.grid_remove()

    def new_mission(self, confirm=True):
        if confirm and not messagebox.askyesno("New Mission", "This will clear all current mission data. Are you sure?"):
            return

        self.state.reset_inputs()
        self.update_mortar_inputs()
        self.clear_solution()
        self.mission_log.clear_log()
        self.state.last_coords = {}
        self.map_view_widget.plot_positions()

    def save_log_as(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Save Mission Log As..."
        )
        if not filepath:
            return
        try:
            with open(filepath, 'w') as f:
                json.dump(self.mission_log.get_log_data(), f, indent=4)
            messagebox.showinfo("Success", "Mission log saved successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save mission log: {e}")


    def load_file_smart(self):
        """
        Opens a file dialog, reads the selected JSON file, and intelligently
        determines if it's a mission log or a TRP list, then loads it.
        """
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Load Mission Log or TRP List"
        )
        if not filepath:
            return

        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            if not isinstance(data, list):
                messagebox.showerror("Error", "Invalid file format. Expected a list of objects.")
                return

            if data and isinstance(data[0], dict) and "mortars" in data[0]:
                # Appears to be a mission log
                self.mission_log.load_log_data(data)
                messagebox.showinfo("Success", "Mission log loaded successfully.")
            elif data and isinstance(data[0], dict) and all(key in data[0] for key in ['grid', 'elev', 'name', 'status']):
                # Appears to be a TRP list
                self.trp_view.load_trp_list_from_data(data) # Call a new method in TRPView
                messagebox.showinfo("Success", "TRP list loaded successfully.")
            else:
                messagebox.showwarning("Load Warning", "Could not determine file type. Please ensure it's a valid mission log or TRP list.")

        except json.JSONDecodeError:
            messagebox.showerror("Error", "Invalid JSON file. Please select a valid mission log or TRP list.")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred while loading the file: {e}")

    def load_map_image_and_view(self):
        map_name = self.state.selected_map_var.get()
        if not map_name:
            self.state.map_image = None
            self.map_view_widget.plot_positions()
            return

        map_path = "" # Define here to be available in except block
        try:
            # Use the config_manager to get the correct base directory for maps
            map_path = os.path.join(self.config_manager.maps_dir, map_name)
            
            if os.path.exists(map_path):
                self.state.map_image = Image.open(map_path)
                map_x_max = self.state.map_x_max_var.get()
                map_y_max = self.state.map_y_max_var.get()
                self.state.map_view = [0, 0, map_x_max, map_y_max]
            else:
                self.state.map_image = None
                messagebox.showerror("Map Error", f"Map file not found.\n\nPyInstaller check: The application expected to find the map at the following path, but it does not exist:\n\n{map_path}")
        except Exception as e:
            self.state.map_image = None
            messagebox.showerror("Map Loading Error", f"An error occurred while loading the map image:\n\n{e}\n\nAttempted path:\n{map_path}")
        
        self.map_view_widget.plot_positions()

    def on_closing(self):
        """Handles the window closing event to gracefully shut down the worker thread."""
        self.task_queue.put(None)  # Send sentinel to worker
        self.destroy()

    def load_trp_to_main_from_log(self):
        log_entries = self.mission_log.get_log_data()
        if not log_entries:
            messagebox.showinfo("No Log Entries", "The mission log is empty. Please log a mission first.")
            return

        # Create a list of display names for the dialog
        display_entries = []
        for i, entry in enumerate(log_entries):
            # For TRP_BATCH_RESULT, display TRP Name and Status
            if entry.get("type") == "TRP_BATCH_RESULT":
                trp_data = entry.get("data", {})
                display_entries.append(f"TRP Batch: {trp_data.get('TRP Name', 'Unknown')} ({trp_data.get('Status', 'N/A')})")
            else:
                # For regular missions, display Target Name and Grid
                display_entries.append(f"{entry.get('target_name', 'Unknown Mission')} ({entry.get('calculated_target_grid', 'N/A')})")

        dialog = ListSelectDialog(self, "Select Mission Log Entry", display_entries, self.is_dark_mode)
        selected_display_name = dialog.result

        if selected_display_name:
            # Find the original mission data based on the selected display name
            selected_mission_data = None
            for i, entry in enumerate(log_entries):
                if entry.get("type") == "TRP_BATCH_RESULT":
                    trp_data = entry.get("data", {})
                    if selected_display_name == f"TRP Batch: {trp_data.get('TRP Name', 'Unknown')} ({trp_data.get('Status', 'N/A')})":
                        selected_mission_data = entry
                        break
                else:
                    if selected_display_name == f"{entry.get('target_name', 'Unknown Mission')} ({entry.get('calculated_target_grid', 'N/A')})":
                        selected_mission_data = entry
                        break
            
            if selected_mission_data:
                # Extract TRP data from the selected mission
                if selected_mission_data.get("type") == "TRP_BATCH_RESULT":
                    # For batch results, we need to select a specific TRP from the batch
                    # This is more complex, as the user wants to load a single TRP.
                    # For now, let's assume they select a regular mission or a single TRP from the TRP tab.
                    # If they select a TRP_BATCH_RESULT, we can't directly load a single TRP from it here.
                    # This button is for loading a *single* target from the log.
                    messagebox.showwarning("Selection Error", "Please select a regular mission entry, not a TRP batch result.")
                    return
                
                target_grid = selected_mission_data.get("calculated_target_grid")
                target_elev = selected_mission_data.get("target_elev")

                if target_grid and target_elev is not None:
                    self.state.trp_grid_var.set(target_grid)
                    self.state.trp_elev_var.set(target_elev)
                    self.state.targeting_mode_var.set("Grid")
                    self.on_targeting_mode_change()
                    messagebox.showinfo("TRP Loaded", f"Target '{selected_mission_data.get('target_name', 'Unknown')}' loaded to Main tab.")
                else:
                    messagebox.showwarning("Load Error", "Selected mission entry does not contain valid target grid or elevation.")
            else:
                messagebox.showwarning("Selection Error", "Could not find selected mission data.")

if __name__ == "__main__":
    app = MortarCalculatorApp()
    app.mainloop()
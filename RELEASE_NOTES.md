### Release Notes - v1.4.4

#### ✨ New Features
*   **TRP List Management:** Implemented dedicated "Save TRP List" and "Load TRP List" functionalities within the TRP tab.
    *   Users can now save and load pure TRP data (grid, elevation, name, status) independently of the main mission log.
    *   The `Operation_GoldRush_TRP_List.json` file has been updated to reflect this pure TRP list format.
*   **Unified Load File Functionality:** Implemented a single "Load File" button that intelligently detects and loads either a mission log or a TRP list from a selected JSON file.
*   **Mortar Data Persistence:** Refactored mortar input handling to preserve existing mortar data, including locked fields, when the number of mortars is changed or a new mission is loaded.
*   **Automatic TRP Mode Switch:** The "Calculate All TRPs" button in the TRP tab now automatically switches the main page's targeting mode to "Grid (TRP)" and navigates to the main tab.

#### 🐛 Bug Fixes
*   **TRP Log Saving:** Corrected an issue where TRP batch calculation results were saving gun information to the mission log. Only TRP location data is now saved.
*   **TRP Log Display:** Fixed an issue where the Mission Log displayed default coordinates for TRP batch results instead of the original TRP grid.
*   **Improved TRP Load Warning:** Enhanced the "Load TRP List" function to provide a more informative warning if a mission log file is mistakenly selected, guiding the user to the correct loading function.

#### 🤖 Roo's Notes
*   This release focused on refining the TRP management workflow and improving data persistence for mortar inputs. The separation of TRP list saving/loading from the main mission log provides greater flexibility for users.
*   The `update_mortar_inputs` method was refactored to intelligently retain existing mortar data when the number of active mortars changes, addressing a key user feedback point regarding data loss.
*   Improvements to TRP logging and loading ensure data accuracy and a smoother user experience when working with TRP lists.
*   The automatic mode switch and tab navigation when calculating TRPs from the list streamline the user's workflow.

---

### Release Notes - v1.4.3

#### 🐛 Bug Fixes
*   **Elevation Correction Logic:** Corrected the elevation difference calculation. For uphill targets (positive elevation difference), `delev` is now subtracted from the base elevation. For downhill targets (negative elevation difference), `delev` is added to the base elevation. This ensures accurate firing solutions regardless of terrain.
*   **FO Correction Logic:** Reworked the Left/Right and Add/Drop corrections to be applied relative to the Forward Observer's (FO) perspective. "Drop" now correctly moves the target closer to the FO (negative value), "Add" moves it further (positive value), "Left" moves it to the left of the FO's azimuth (negative value), and "Right" moves it to the right (positive value). This provides a more intuitive and accurate correction system.

---

### Release Notes - v1.4.2

#### ✨ New Features
*   **TRP Tab:** Introduced a new "TRP" tab for managing Target Reference Points.
    *   Users can add, remove, and clear TRPs with grid, elevation, and name.
    *   TRPs are displayed in a table with their calculation status (Solution Found, No Solution, Error).
    *   **TRP Details View:** Selecting a TRP in the list now displays its Grid, Elevation, Name/ID, and Status in a dedicated details panel.
*   **Batch TRP Calculation:** Implemented a "Calculate All TRPs" button on the TRP tab.
    *   Calculates solutions for all TRPs in the list using current mortar positions.
    *   Displays per-gun error messages for out-of-range or invalid solutions in the main UI's solution tabs and quick fire data.
    *   Logs only successfully calculated (green) TRP-mortar solutions as individual mission entries in the main "Fire Mission Log".
    *   Clears the in-memory mission log before batch calculation to show only current results (without affecting saved log files).
    *   **UI Performance Improvement:** Batch calculations now run more smoothly in the background, with only the TRP list status and mission log updating during the process. The map updates once at the end to show all calculated TRP targets.
*   **Load TRPs from Log:** Added a "Load TRPs from Mission Log" button on the TRP tab.
    *   Allows importing TRP data from existing mission log files into the TRP list.
    *   Robustly handles various log formats and missing data.
*   **Load TRP from TRP List (Main Tab):** The "Load TRP from TRP List" button has been relocated from the TRP tab to the "3. Targeting Data" frame on the Main tab.
    *   It is now conditionally visible only when "Grid (TRP)" targeting mode is selected.
    *   Opens a pop-up dialog listing *all* TRPs from the currently loaded TRP list (regardless of calculation status).
    *   Selecting a TRP auto-fills its grid and elevation into the main UI's TRP input fields, sets the targeting mode to "Grid", and auto-calculates.
*   **Load TRP from Log (Main Tab):** Added a "Load TRP from Log" button to the "Quick Fire Data" section on the Main tab.
    *   Allows selecting any individual mission entry from the main mission log to populate the main UI's TRP input fields.
*   **TRPSelectDialog Scrolling:** The TRP selection pop-up dialog (`TRPSelectDialog`) now handles its own mouse wheel scrolling, preventing interference with the main application's scroll.
*   **Refined Map Display in TRP Mode:** The Forward Observer (FO) position is no longer plotted on the map when in "Grid (TRP)" targeting mode, providing a cleaner and more relevant view.
*   **Improved TRP Grid Formatting:** All TRP grid inputs and displays now consistently use a 10-digit format with leading zeros, improving data consistency and readability.
*   **Enhanced TRP List Visuals:** The "Solution Found" text in the TRP list now uses a more vibrant green in dark mode and black in light mode, improving visibility and contrast.

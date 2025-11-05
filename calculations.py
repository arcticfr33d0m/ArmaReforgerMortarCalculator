import math
from ballistics import BALLISTIC_DATA

def interpolate(x, x1, y1, x2, y2):
    """Helper function for linear interpolation."""
    if x2 == x1:
        return y1
    return y1 + (x - x1) * (y2 - y1) / (x2 - x1)

def parse_grid(grid_str):
    """Parses an 8 or 10 digit grid string into easting and northing."""
    grid_str = grid_str.replace(" ", "")
    
    if len(grid_str) == 8:
        half = len(grid_str) // 2
        easting = int(grid_str[:half]) * 10
        northing = int(grid_str[half:]) * 10
    elif len(grid_str) == 10:
        half = len(grid_str) // 2
        easting = int(grid_str[:half])
        northing = int(grid_str[half:])
    else:
        raise ValueError(f"Grid must be 8 or 10 digits, but got {len(grid_str)} digits.")
        
    return easting, northing

def calculate_target_coords(fo_grid_str, fo_azimuth_deg, fo_dist, fo_elev_diff, corr_lr, corr_add_drop):
    """
    Calculates the target's coordinates based on FO data and corrections.
    Corrections (Add/Drop, Left/Right) are applied relative to the FO's perspective.
    """
    fo_easting, fo_northing = parse_grid(fo_grid_str)
    azimuth_rad = math.radians(fo_azimuth_deg)

    # Calculate initial target position based on FO data
    initial_target_easting = fo_easting + fo_dist * math.sin(azimuth_rad)
    initial_target_northing = fo_northing + fo_dist * math.cos(azimuth_rad)

    # Apply Add/Drop correction along the FO's line of sight
    # Positive corr_add_drop moves target further from FO, negative moves closer
    corrected_easting = initial_target_easting + corr_add_drop * math.sin(azimuth_rad)
    corrected_northing = initial_target_northing + corr_add_drop * math.cos(azimuth_rad)

    # Apply Left/Right correction perpendicular to the FO's line of sight
    # Positive corr_lr moves target to the right of FO's azimuth
    # Negative corr_lr moves target to the left of FO's azimuth
    # Azimuth + 90 degrees (pi/2 radians) for right, Azimuth - 90 degrees for left
    # sin(azimuth + pi/2) = cos(azimuth)
    # cos(azimuth + pi/2) = -sin(azimuth)
    corrected_easting += corr_lr * math.cos(azimuth_rad)
    corrected_northing -= corr_lr * math.sin(azimuth_rad)

    return corrected_easting, corrected_northing

def find_valid_solutions(faction, ammo, distance, elev_diff):
    """Finds all valid firing solutions for a given ammo, distance, and elevation change."""
    valid_solutions = []
    
    faction_data = BALLISTIC_DATA.get(faction)
    if not faction_data:
        raise ValueError(f"Invalid faction: {faction}")
    
    ammo_data = faction_data.get(ammo)
    if not ammo_data:
        raise ValueError(f"Invalid ammo type '{ammo}' for faction '{faction}'")

    for charge, charge_data in ammo_data.items():
        charge_ranges = charge_data['ranges']
        sorted_ranges = sorted(charge_ranges.keys())
        if not (sorted_ranges[0] <= distance <= sorted_ranges[-1]):
            continue

        for i in range(len(sorted_ranges) - 1):
            if sorted_ranges[i] <= distance <= sorted_ranges[i+1]:
                r1, r2 = sorted_ranges[i], sorted_ranges[i+1]
                d1, d2 = charge_ranges[r1], charge_ranges[r2]
                
                base_elev = interpolate(distance, r1, d1["elev"], r2, d2["elev"])
                base_tof = interpolate(distance, r1, d1["tof"], r2, d2["tof"])
                base_delev = interpolate(distance, r1, d1["delev"], r2, d2["delev"])
                
                # Apply elevation correction: subtract for uphill (positive elev_diff), add for downhill (negative elev_diff)
                final_elevation = base_elev - (elev_diff / 100) * base_delev
                
                valid_solutions.append({
                    "charge": charge,
                    "elev": final_elevation,
                    "tof": base_tof,
                    "dispersion": charge_data['dispersion']
                })
                break
    return valid_solutions

def check_target_on_mortar_fo_axis(mortar_coords, fo_coords, target_coords, lane_width=100):
    """
    Checks if the target is within a 'lane' between the mortar and the FO,
    which can lead to unreliable corrections.
    Returns True if the correction is unreliable, False otherwise.
    """
    # Vectors
    v_mf = (fo_coords[0] - mortar_coords[0], fo_coords[1] - mortar_coords[1]) # Mortar to FO
    v_mt = (target_coords[0] - mortar_coords[0], target_coords[1] - mortar_coords[1]) # Mortar to Target

    len_sq_mf = v_mf[0]**2 + v_mf[1]**2
    if len_sq_mf == 0:
        return False # Mortar and FO are at the same spot, no axis to be on

    # 1. Check if the projection of the target lies on the segment between mortar and FO
    dot_product = v_mf[0] * v_mt[0] + v_mf[1] * v_mt[1]
    if not (0 < dot_product < len_sq_mf):
        return False

    # 2. Check if the target is close to the line (within the lane)
    # Perpendicular distance from target to the line defined by mortar-FO
    cross_product = abs(v_mf[0] * v_mt[1] - v_mf[1] * v_mt[0])
    distance_from_line = cross_product / math.sqrt(len_sq_mf)
    
    return distance_from_line < (lane_width / 2)

def check_danger_close(fo_coords, target_coords, dispersion, danger_close_distance=100):
    """
    Checks if the target's dispersion radius is dangerously close to the FO.
    Returns True if danger close, False otherwise.
    """
    distance_sq = (target_coords[0] - fo_coords[0])**2 + (target_coords[1] - fo_coords[1])**2
    return distance_sq <= (dispersion + danger_close_distance)**2

def calculate_new_fo_data(fo_coords, target_coords):
    """
    Calculates the new azimuth and distance from the FO to the corrected target.
    """
    delta_easting = target_coords[0] - fo_coords[0]
    delta_northing = target_coords[1] - fo_coords[1]

    new_dist = math.sqrt(delta_easting**2 + delta_northing**2)
    new_azimuth_rad = math.atan2(delta_easting, delta_northing)
    new_azimuth_deg = math.degrees(new_azimuth_rad)
    if new_azimuth_deg < 0:
        new_azimuth_deg += 360

    return new_azimuth_deg, new_dist

def calculate_regular_mission(mortars, target_coords, faction, ammo):
    """Calculates a regular fire mission for one or more mortars,
    returning results for each mortar, including error status if no solution."""
    mortar_results = []
    for mortar in mortars:
        result_for_mortar = {
            "mortar": mortar,
            "target_coords": target_coords,
            "least_tof": None,
            "most_tof": None,
            "error": None
        }
        try:
            mortar_e, mortar_n = mortar['coords']
            target_e, target_n, target_elev = target_coords
            elev_diff = target_elev - mortar['elev']
            
            dist = math.sqrt((target_e - mortar_e)**2 + (target_n - mortar_n)**2)
            
            valid_solutions = find_valid_solutions(faction, ammo, dist, elev_diff)
            if not valid_solutions:
                result_for_mortar["error"] = f"No valid solution for {mortar.get('callsign', 'gun')}"
            else:
                valid_solutions.sort(key=lambda x: x['tof'])
                
                least_tof_solution = valid_solutions[0]
                # Find a most_tof solution that is distinct from the least_tof one
                most_tof_solution = next((s for s in reversed(valid_solutions) if s['charge'] != least_tof_solution['charge']), least_tof_solution)

                result_for_mortar["least_tof"] = least_tof_solution
                result_for_mortar["most_tof"] = most_tof_solution
        except ValueError as e:
            result_for_mortar["error"] = str(e)
        except Exception as e:
            result_for_mortar["error"] = f"Calculation error for {mortar.get('callsign', 'gun')}: {e}"
        
        mortar_results.append(result_for_mortar)
    return mortar_results

def _calculate_barrage(mortars, target_coords, faction, ammo, sort_key='tof', reverse=False):
    """Helper function to calculate barrage missions,
    returning results for each mortar, including error status if no solution."""
    mortar_results = []
    for mortar in mortars:
        result_for_mortar = {
            "mortar": mortar,
            "target_coords": target_coords,
            "least_tof": None,
            "most_tof": None,
            "error": None
        }
        try:
            mortar_e, mortar_n = mortar['coords']
            target_e, target_n, target_elev = target_coords
            dist = math.sqrt((target_e - mortar_e)**2 + (target_n - mortar_n)**2)
            elev_diff = target_elev - mortar['elev']
            
            valid_solutions = find_valid_solutions(faction, ammo, dist, elev_diff)
            if not valid_solutions:
                result_for_mortar["error"] = f"No valid solution for {mortar.get('callsign', 'gun')}"
            else:
                valid_solutions.sort(key=lambda x: x[sort_key], reverse=reverse)
                best_solution = valid_solutions[0]
                
                result_for_mortar["least_tof"] = best_solution
                result_for_mortar["most_tof"] = best_solution # For barrage, least and most are the same
        except ValueError as e:
            result_for_mortar["error"] = str(e)
        except Exception as e:
            result_for_mortar["error"] = f"Calculation error for {mortar.get('callsign', 'gun')}: {e}"
        
        mortar_results.append(result_for_mortar)
    return mortar_results

def calculate_small_barrage(mortars, target_coords, faction, ammo):
    """Calculates a small barrage, prioritizing the round with the shortest Time of Flight (ToF)."""
    return _calculate_barrage(mortars, target_coords, faction, ammo, sort_key='tof', reverse=False)

def calculate_large_barrage(mortars, target_coords, faction, ammo):
    """Calculates a large barrage, prioritizing the round with the longest Time of Flight (ToF)."""
    return _calculate_barrage(mortars, target_coords, faction, ammo, sort_key='tof', reverse=True)

def calculate_creeping_barrage(mortars, initial_target, creep_direction, faction, ammo, creep_spread=1.0):
    """Calculates a creeping barrage, returning results for each mortar,
    including error status if no solution."""
    if len(mortars) < 3:
        # This is a global error for the mission type, not per-mortar
        raise ValueError("Creeping barrage requires at least 3 mortars.")
    
    mortar_results = []
    
    # Find the best round (least dispersion) using the first mortar as a reference
    best_charge = None
    min_dispersion = float('inf')
    
    try:
        mortar_e, mortar_n = mortars[0]['coords']
        target_e, target_n, target_elev = initial_target
        dist = math.sqrt((target_e - mortar_e)**2 + (target_n - mortar_n)**2)
        elev_diff = target_elev - mortars[0]['elev']
        
        possible_solutions = find_valid_solutions(faction, ammo, dist, elev_diff)
        if not possible_solutions:
            raise ValueError("No valid charges for creeping barrage.")
            
        for sol in possible_solutions:
            if sol['dispersion'] < min_dispersion:
                min_dispersion = sol['dispersion']
                best_charge = sol['charge']
    except Exception as e:
        # If we can't even determine the best charge, it's a global failure for creeping barrage
        raise ValueError(f"Error determining best charge for creeping barrage: {e}")

    creep_rad = math.radians(creep_direction)
    
    for i, mortar in enumerate(mortars):
        result_for_mortar = {
            "mortar": mortar,
            "target_coords": None, # Will be set below
            "least_tof": None,
            "most_tof": None,
            "error": None
        }
        try:
            offset_dist = i * min_dispersion * creep_spread
            
            new_target_e = initial_target[0] + offset_dist * math.sin(creep_rad)
            new_target_n = initial_target[1] + offset_dist * math.cos(creep_rad)
            new_target_coords = (new_target_e, new_target_n, initial_target[2])
            result_for_mortar["target_coords"] = new_target_coords
            
            mortar_e, mortar_n = mortar['coords']
            dist = math.sqrt((new_target_e - mortar_e)**2 + (new_target_n - mortar_n)**2)
            elev_diff = new_target_coords[2] - mortar['elev']
            
            valid_solutions = find_valid_solutions(faction, ammo, dist, elev_diff)
            
            final_solution = None
            for sol in valid_solutions:
                if sol['charge'] == best_charge:
                    final_solution = sol
                    break
            
            if not final_solution:
                result_for_mortar["error"] = f"Could not find solution with charge {best_charge} for {mortar.get('callsign', 'gun')}"
            else:
                result_for_mortar["least_tof"] = final_solution
                result_for_mortar["most_tof"] = final_solution
        except ValueError as e:
            result_for_mortar["error"] = str(e)
        except Exception as e:
            result_for_mortar["error"] = f"Calculation error for {mortar.get('callsign', 'gun')}: {e}"
            
        mortar_results.append(result_for_mortar)
        
    return mortar_results
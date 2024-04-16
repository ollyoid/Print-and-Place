#! /usr/bin/env python3
#  A command line utility that inserts Gcode to fill plated though holes in a 3D printed circuit board

import sys
import os
import argparse
from svgpathtools import svg2paths
import json


# Parse command line arguments
def parse_args():
    def check_extension(filename, extension):
        if not filename.lower().endswith(extension):
            raise argparse.ArgumentTypeError(f"File must have a {extension} extension")
        if not os.path.isfile(filename):
            raise argparse.ArgumentTypeError(f"File {filename} does not exist")
        return filename
    
    parser = argparse.ArgumentParser(description='Inject Gcode to fill plated though holes in a 3D printed circuit board')
    parser.add_argument('in_gcode', help='Input Gcode file', type=lambda f: check_extension(f, '.gcode'))
    parser.add_argument('drl', help='Input drill file', type=lambda f: check_extension(f, '.drl'))
    parser.add_argument('cuts', help='Input cuts file', type=lambda f: check_extension(f, '.svg'))
    parser.add_argument('out_gcode', help='Output Gcode file')
    args = parser.parse_args()

    # Check if output file exists and prompt for overwrite
    if os.path.isfile(args.out_gcode):
        should_overwrite = input(f"File {args.out_gcode} already exists. Do you want to overwrite it? (y/n): ")
        if should_overwrite.lower() != 'y':
            print("Exiting without overwriting the file.")
            sys.exit()
    return args


def find_svg_centre(svg_file_path):
    # Parse the SVG file
    paths, attributes = svg2paths(svg_file_path)
    
    # Initialize min and max coordinates to None
    min_x, min_y, max_x, max_y = None, None, None, None
    
    # Iterate through all the paths to find the overall bounding box
    for path in paths:
        # Get the bounding box of the current path
        path_min_x, path_max_x, path_min_y, path_max_y = path.bbox()
        
        # Update the overall bounding box
        min_x = path_min_x if min_x is None else min(min_x, path_min_x)
        min_y = path_min_y if min_y is None else min(min_y, path_min_y)
        max_x = path_max_x if max_x is None else max(max_x, path_max_x)
        max_y = path_max_y if max_y is None else max(max_y, path_max_y)
    
    centre_x = (min_x + max_x) / 2
    centre_y = (min_y + max_y) / 2
    return centre_x, centre_y


def find_gcode_objects_center(gcode_file_path):
    # Open and read the G-code file
    with open(gcode_file_path, 'r') as file:
        lines = file.readlines()
    
    # Initialize variables to hold the bounding box coordinates
    min_x, min_y, max_x, max_y = None, None, None, None
    
    # Search for the objects_info line
    for line in lines:
        if "objects_info" in line:
            # Extract the JSON part from the line
            json_str = line.split("=", 1)[1].strip()
            objects_info = json.loads(json_str)
            
            # Iterate through all objects and their polygons
            for obj in objects_info["objects"]:
                for point in obj["polygon"]:
                    x, y = point
                    
                    # Update the bounding box coordinates
                    if min_x is None or x < min_x:
                        min_x = x
                    if min_y is None or y < min_y:
                        min_y = y
                    if max_x is None or x > max_x:
                        max_x = x
                    if max_y is None or y > max_y:
                        max_y = y
    
    # Calculate the center of the bounding box
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    
    # Return the center point
    return center_x, center_y

def parse_drill_file(drill_file_path, tool="T1"):
    holes = []
    current_tool = None  # Track the current tool being used
    with open(drill_file_path, 'r') as file:
        for line in file:
            line = line.strip()
            if line.startswith('T') and not 'C' in line:  # Check if the line is selecting a tool, ignore tool definition lines
                current_tool = line  # Update the current tool
            if line.startswith('X') and 'Y' in line and current_tool == tool:
                # Extract the X and Y coordinates
                parts = line.split('Y')
                x = parts[0][1:]  # Remove the 'X' prefix
                y = parts[1]
                holes.append((float(x), float(y)))
    return holes

def get_gcode_sections(gcode_file_path):
    sections = []
    current_section = "Header"
    current_start_line = 0

    with open(gcode_file_path, 'r') as file:
        for i, line in enumerate(file):
            if line.startswith(';TYPE:'):
                sections.append((current_section, current_start_line, i))
                current_section = line.split(':')[1].strip()
                current_start_line = i + 1
        sections.append((current_section, current_start_line, i))

    return sections

def get_tool_changes(gcode_file_path):
    tool_changes = []
    with open(gcode_file_path, 'r') as file:
        for i, line in enumerate(file):
            if line.startswith("T"):
                tool_changes.append((i, line.strip()))
    return tool_changes


def get_last_coords(lines):
    last_x, last_y, last_z = None, None, None
    for line in lines:
        # Check for movement commands that include X, Y, or Z coordinates
        if line.startswith("G0") or line.startswith("G1"):
            parts = line.split()
            for part in parts:
                if part.startswith('X'):
                    last_x = float(part[1:])
                elif part.startswith('Y'):
                    last_y = float(part[1:])
                elif part.startswith('Z'):
                    last_z = float(part[1:])
    
    # Return the last X, Y, Z coordinates, head, and tail
    return (last_x, last_y, last_z)

def generate_gcode_for_holes(holes, last_pos, extrusion_amount=0.48, retraction_amount=7.5):
    x, y, z = last_pos
    gcode = []
    move_above_height = 5 + z  # Move 5mm above the last Z-height

    # Set the temp a bit higher
    gcode.append(f"M104 S240\n")

    gcode.append(f"G0 Z{move_above_height}F4200\n")
    for x, y in holes:
        # Move above the hole
        gcode.append(f"G0 X{x} Y{y} Z{move_above_height}F4200\n")
        # Lower down to the point
        gcode.append(f"G0 Z{z-0.05}F4200\n")
        # Un-retract
        gcode.append(f"G1 E{retraction_amount} F4200\n")
        # Extrude some plastic
        gcode.append(f"G1 E{extrusion_amount}F4200\n")
    	# Wait for 1 second
        gcode.append(f"G4 P1000\n")
        # Retract a bit
        gcode.append(f"G1 E-{retraction_amount} F4200\n")
        # Wait for 1 second
        gcode.append(f"G4 P1000\n")
        #move a  mm to the right
        gcode.append(f"G0 X{x+1} Y{y} F4200\n")
        # Move up back to 5mm above before going to the next hole
        gcode.append(f"G0 Z{move_above_height}F4200\n")
    # Move back to the last x, y position
    gcode.append(f"G0 X{x} Y{y} F4200\n")
    # Move back to the last z position
    gcode.append(f"G0 Z{z} F4200\n")

    # Set the temp back to 220
    gcode.append(f"M104 S220\n")

    return gcode

def write_gcode(out_gcode, combined_gcode):
    with open(out_gcode, 'w') as out_file:
        for line in combined_gcode:
                out_file.write(line)  # Ensure each G-code command is on a new line

# Entry point
def main():
    args = parse_args()

    # Find the centre of the SVG bounding box
    design_centre = find_svg_centre(args.cuts)

    # Find the centre of the G-code objects footprints
    gcode_centre = find_gcode_objects_center(args.in_gcode)

    # Calculate the offset between the two centres to usee for drill points
    centre_delta = (gcode_centre[0] - design_centre[0], gcode_centre[1] - design_centre[1])

    # Parse the drill file
    holes = parse_drill_file(args.drl)

    ## Add offset to holes
    holes = [(round(x + centre_delta[0], 2), round(y + centre_delta[1] +2*design_centre[1], 2)) for x, y in holes]

    # Parse gcode sections
    sections = get_gcode_sections(args.in_gcode)

    # Find lines where there are tool changes
    tool_changes = get_tool_changes(args.in_gcode)

    if len(tool_changes) < 1:
        raise ValueError("No tool changes found in the input G-code file")
    elif len(tool_changes) == 1:
        raise ValueError("Only one tool change found in the input G-code file. At least two tools are required.")
    elif len(tool_changes) > 2:
        raise ValueError("More than two tool changes found in the input G-code file. Only two tool changes are supported at the moment.")
    
    # Line where Non-conductive to conductive tool change happens
    tool_change = tool_changes[1][0]

    wipe_section = next((s for s in sections if s[0] == "Wipe tower" and s[1] > tool_change), None)

    if wipe_section is None:
        raise ValueError("No wipe tower section found after the tool change")
    
    insertion_point = wipe_section[2]

    # Split the gcode into two strings, before and after the insertion point
    with open(args.in_gcode, 'r') as file:
        lines = file.readlines()
        head = lines[:insertion_point+1]
        tail = lines[insertion_point+1:]

    last_coords = get_last_coords(head)

    # Generate Gcode for holes
    hole_gcode = generate_gcode_for_holes(holes, last_coords)

    # Insert g-code for filament change
    head.insert(tool_change + 1, "M600\n")
    head.insert(tool_change + 2, "M400\n")

    # Combine head, hole_gcode, and tail
    combined_gcode = head + hole_gcode + tail

    # Write the combined G-code to the output file
    write_gcode(args.out_gcode, combined_gcode)

    print(f"Combined G-code has been written to {args.out_gcode}")


if __name__ == "__main__":
    main()
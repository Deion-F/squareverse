import gc
from time import sleep
import pygame
from graphics_pygame import GraphWin, Point, Rectangle, color_rgb, Line
from random import randint, randrange, choice
from copy import copy
from mongo import Mongo
from pymongo import UpdateOne
from typing import Tuple, Optional
import pprint
import time


class Squareverse():
    
    
    def __init__(self, squareverse_id, squareverse_name):
        self.squareverse_id = squareverse_id
        self.squareverse_name = squareverse_name
        self.squareverse_size = 0
        self.squareverse_grid_spacing = 0       
        self.created_squares = []        
        self.square_positions = set()
        # Cache for square positions and collision checks
        self._position_cache = {}
        self._collision_cache = {}
        # -----------------------------------------------------
        # self.mongo_client = Mongo()
        # gc.collect(generation=2) # TESTING
        # gc.disable() # TESTING


    def showSquareverseMenu(self):
        valid_options = ["s", "d", "a", "m", "e"]
        debugging = False
        while True:
            user_selection = input("\n\nSelect an option:\n(s) Spawn Squares\n(d) Delete # of Squares\n(a) Delete All Squares\n(m) Move Squares\n(e) End Squareverse Simulation\n\nOption: ")
            try:
                if user_selection.lower() not in valid_options:
                    raise ValueError("E: that was not a valid option!")
            except ValueError as e:
                print(e)
                continue
            if user_selection == "s":
                print(f"\nMax # of Squares that can be spawned: {self.max_number_of_squares}") # INFO
                number_of_squares = input(f"\n\nEnter number of Squares to spawn (m = max, h = 50%, q = 25%)\nNumber of empty grids remaining: {self.max_number_of_squares - len(self.window.squares)}\n:")
                if number_of_squares == "m":
                    number_of_squares = (self.max_number_of_squares - len(self.window.squares))              
                elif number_of_squares == "h":
                    number_of_squares = (self.max_number_of_squares - len(self.window.squares)) // 2 
                elif number_of_squares == "q":
                    number_of_squares = (self.max_number_of_squares - len(self.window.squares)) // 4
                else:
                    pass
                self.createSquares(int(number_of_squares))
            elif user_selection == "d":
                pass
            elif user_selection == "a":
                if debugging == True:
                    print(f"\nDEBUG: Length of Square objects array: {len(self.window.squares)}\n")
                
                for square in self.window.squares[:]:
                    self.destroySquare(square)
                # for sq
            elif user_selection == "m":
                self.moveAllSquares()
            else:
                if debugging:
                    start_time = time.time()
                
                self.destroySquareverse()
                
                if debugging:
                    total_time = time.time() - start_time # DEBUG
                    print(f"\nTime to destroy Squareverse: {total_time}\n\n") # DEBUG
                
                break
        # enable Garbage Collection before exiting
        gc.collect(generation=2) # TESTING
        gc.enable() # TESTING
    
    
    def createSquareverseWindow(self, squareverse_size, squareverse_grid_spacing):   
        debugging = False
        # if debugging:
            # gc.disable() # disables Garbage Collection to speed up creation of Squares
        self.square_objects = {}
        
        # Initialize update batching containers
        self._pending_updates = []
        self._geometry_updates = []
        
        # connects to MongoDB
        self.mongo_client = Mongo()   
        
        # sets parent Squareverse window configuration
        # self.window_background_color = color_rgb(47, 47, 47)
        self.window_background_color = color_rgb(82, 69, 56)
        self.grid_color = color_rgb(0, 0, 0)
        self.squareverse_size = squareverse_size
        self.squareverse_grid_spacing = squareverse_grid_spacing
        self.squareverse_window_size = self.squareverse_size + (self.squareverse_grid_spacing * 2)
        self.max_number_of_squares = int(round((self.squareverse_size / self.squareverse_grid_spacing)) ** 2)
        
        # records coordinates for parent Squareverse border and center point (if needed later)
        self.top_border = self.squareverse_grid_spacing
        self.bottom_border = self.squareverse_size + self.squareverse_grid_spacing
        self.left_border = self.squareverse_grid_spacing
        self.right_border = self.squareverse_size + self.squareverse_grid_spacing
        self.center_point_coordinate = ((self.squareverse_size + self.squareverse_grid_spacing) + self.squareverse_grid_spacing) // 2
        self.center_point = Point(self.center_point_coordinate, self.center_point_coordinate) # TESTING
        # self.center_point.setFill("Orange") #testing
        # self.window = GraphWin(title = self.squareverse_name, width = self.squareverse_window_size, height = self.squareverse_window_size, autoflush=False) # creates parent Squareverse window with auto-update disabled
        self.window = GraphWin(title = self.squareverse_name, width = self.squareverse_window_size, height = self.squareverse_window_size) # creates parent Squareverse window with auto-update enabled
        self.window.setBackground(self.window_background_color)
        # creates dictionary of valid coordinate transformations when moving parent Square
        self.valid_directions = {
        "up": {
            "x": 0, 
            "y": (self.squareverse_grid_spacing * - 1), 
            "i": "down"
            }, 
        "down": {
            "x": 0, 
            "y": self.squareverse_grid_spacing, 
            "i": "up"
            }, 
        "left": {
            "x": (self.squareverse_grid_spacing * - 1), 
            "y": 0,
            "i": "right"
            },
        "right": {
            "x": self.squareverse_grid_spacing, 
            "y": 0,
            "i": "left"
            }}
        
        # print(f"\n\n***Squareverse Values***\nSquareverse ID: [{self.squareverse_id}]\nSquareverse Name: [{self.squareverse_name}]\nSquareverse Size: [{self.squareverse_size}px]\nSquareverse Grid Spacing: [{self.squareverse_grid_spacing}px]\nSquareverse Window Size: [{self.squareverse_window_size}px]") # DEBUG
        # self.mongo_client.insert_valid_directions(squareverse_grid_spacing) # TESTING

        # updates parent squareverse window
        # self.window.manualUpdate() # TESTING
        # self.window.flush()

        # creates parent Squareverse grid
        debugging = True
        self.createSquareverseGrid()


    def createSquareverseGrid(self):
        """Create grid using pygame drawing."""
        debugging = True
        self.vertical_starting_point = self.squareverse_grid_spacing
        self.horizontal_starting_point = self.squareverse_grid_spacing
        self.number_of_lines = int(round((self.squareverse_size // self.squareverse_grid_spacing), 0) + 1)
        
        # Handle any pending events
        self.window._handle_events()
        
        # First clear the screen with background color
        self.window.screen.fill(self.window_background_color)
        
        # Create and store grid lines
        self.grid_lines = []
        
        # Draw vertical lines
        for x in range(self.number_of_lines):
            start_pos = (self.horizontal_starting_point + (x * self.squareverse_grid_spacing), self.vertical_starting_point)
            end_pos = (self.horizontal_starting_point + (x * self.squareverse_grid_spacing), self.squareverse_size + self.vertical_starting_point)
            line = Line(Point(*start_pos), Point(*end_pos))
            line.setOutline(self.grid_color)
            line.draw(self.window)
            self.grid_lines.append(line)
            
        # Draw horizontal lines
        for y in range(self.number_of_lines):
            start_pos = (self.horizontal_starting_point, self.vertical_starting_point + (y * self.squareverse_grid_spacing))
            end_pos = (self.squareverse_size + self.horizontal_starting_point, self.vertical_starting_point + (y * self.squareverse_grid_spacing))
            line = Line(Point(*start_pos), Point(*end_pos))
            line.setOutline(self.grid_color)
            line.draw(self.window)
            self.grid_lines.append(line)
            
        # Force display update
        self.window.update()
        # print(f"\n\n[{self.number_of_lines}] grid lines required") # DEBUG
        # self.max_number_of_squares = int(round((self.squareverse_size / self.squareverse_grid_spacing)) ** 2)


        # for _ in range(self.number_of_lines):

        #     # draws vertical line
        #     first_point = Point(self.vertical_starting_point, self.squareverse_grid_spacing)
        #     second_point = Point(self.vertical_starting_point, (self.squareverse_size + self.squareverse_grid_spacing))
        #     self.vertical_line = Line(first_point, second_point)
           
        #     self.vertical_line.setOutline(self.grid_color)
        #     self.vertical_line.draw(self.window)
            
        #     self.vertical_starting_point = self.vertical_starting_point + self.squareverse_grid_spacing

        #     # draws horizontal line
        #     first_point = Point(self.squareverse_grid_spacing, self.horizontal_starting_point)
        #     second_point = Point((self.squareverse_size + self.squareverse_grid_spacing), self.horizontal_starting_point)
        #     self.horizontal_line = Line(first_point, second_point)
            
        #     self.horizontal_line.setOutline(self.grid_color)
        #     self.horizontal_line.draw(self.window)
            
        #     self.horizontal_starting_point = self.horizontal_starting_point + self.squareverse_grid_spacing

            # # manual window update
            # time.sleep(1)
            # self.window.flush() # TESTING

        # updates parent squareverse window
        # time.sleep(2) # added artificial delay as a reminder that the window is now being manually updated
        # self.window.manualUpdate() # TESTING
        # self.window.flush()
        
        # Creates list of all valid Square coordinates in Mongo
        self.mongo_client.create_parent_squareverse_coordinates(self.squareverse_grid_spacing, self.number_of_lines)

        # self.vertical_center_line = Line(Point(self.center_point_coordinate, self.top_border), Point(self.center_point_coordinate, self.bottom_border)) #testing
        
        # self.horizontal_center_line = Line(Point(self.left_border, self.center_point_coordinate), Point(self.right_border, self.center_point_coordinate)) #testing

        # self.vertical_center_line.setFill("Cyan") #testing
        # self.horizontal_center_line.setFill("Cyan") #testing

        # self.vertical_center_line.draw(self.window) #testing
        # self.horizontal_center_line.draw(self.window) #testing
        # self.center_point.draw(self.window) #testing


    def createSquares(self, number_of_squares):
        debugging = True
        # Fetches list of unoccupied parent Squareverse coordinates from MongoDB (free_space is False if no coordinates available)
        result = self.mongo_client.get_available_parent_squareverse_coordinates(number_of_squares)
        if result is None:
            print(f"\nINFO: Failed to get coordinates from database")
            return
            
        free_space, available_coordinates = result
        mongo_bulk_insert_query = []
        

        if free_space == False or not available_coordinates:
                print(f"\nINFO: There are not enough empty grids remaining")
        else:
            if debugging == True:
                start_time = time.time()   
                # gc.disable() # Disables Garbage Collection to speed up creation of parent Squares
            for coordinate in available_coordinates:
                square_id = coordinate["_id"]
                square = ParentSquare(self, square_id)
                square.top_left_corner_x = coordinate["top_left_corner_x"]
                square.top_left_corner_y = coordinate["top_left_corner_y"]
                square.bottom_right_corner_x = coordinate["bottom_right_corner_x"]
                square.bottom_right_corner_y = coordinate["bottom_right_corner_y"]     
                square.drawSquareBody(self, square.top_left_corner_x, square.top_left_corner_y, square.bottom_right_corner_x, square.bottom_right_corner_y) # Draws parent Square on parent Squareverse window
                # # Updates MongoDB to indicate that parent Squareverse coordinate is occupied (updates indidvidual values)
                # mongo_query = { "_id": square_id }
                # mongo_updated_value = { "$set": { "tkinter_id": square.tkinter_id, "testy.testing": "TESTING" }}
                # self.mongo_client.update_mongodb(mongo_query, mongo_updated_value)
                #--
                self.square_objects[square.tkinter_id] = square
                # Updates MongoDB to indicate that parent Squareverse coordinate is occupied (updates all values in bulk)
                mongo_query = UpdateOne({ '_id': square_id }, { '$set': { 'tkinter_id': square.tkinter_id, 'mass': square.mass }})
                mongo_bulk_insert_query.append(mongo_query)
                #--                                
                # Manually updates parent Squareverse window
                # self.window.manualUpdate() # TESTING
                # self.window.flush()
                #--
                # time.sleep(0.001) # Can be increased to lower CPU usage when spawning parent Squares
            self.mongo_client.update_mongodb_bulk(mongo_bulk_insert_query)
            if debugging == True:
                total_time = time.time() - start_time
                print(f"\nDEBUG: Time to create Squares: {total_time}")
                # print(f"\nList of Square objects: {self.square_objects}\n")
                # gc.enable() # enables Garbage Collection
        debugging = True


    # def createMultipleSquares(self, squares_to_create):

    #     for square in squares_to_create:

    #         self.square.body = Rectangle(Point(top_left_corner_x, top_left_corner_y), Point(bottom_right_corner_x, bottom_right_corner_y))
        
    #         self.square.body.setFill(self.body_color)

    #         self.square.body.setOutline(self.outline_color)
            
    #         self.square.body.draw(squareverse_p.window)
            
    #         self.square.child_squareverse.createSquareverseWindow(squareverse_p.squareverse_size, squareverse_p.squareverse_grid_spacing, self.body_color)

    #         self.child_squareverse.createSquares((self.child_squareverse.max_number_of_squares // 6)) # controls how many child Squares are created
    
    
    # will no longer needed as available coordinates are stored in Mongo
    def duplicateSquareCheck(self, square, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):

        square_coordinates = f"{top_left_corner_x}:{top_left_corner_y}:{bottom_right_corner_x}:{bottom_right_corner_y}"

        if square_coordinates in self.square_positions:

            duplicate_square = True

            # print(f"\n\nA Square already exists @ {square_coordinates}") #D

            return duplicate_square

        else:

            duplicate_square = False

            square.current_coordinates = square_coordinates

            return duplicate_square
    
    
    # # commented to test new logic
    # def moveAllSquares(self):

    #     mouse_clicked = self.window.checkMouse()
       
    #     while mouse_clicked == None:

    #         for square in self.created_squares:
  
    #             square.moveSquare(self)
                    
    #             # mouse_clicked = self.window.checkMouse()
               
    #         mouse_clicked = self.window.checkMouse()


    def moveAllSquares(self):
        """Move all squares with batch updates using pygame."""
        import time
        
        debugging = True
        
        while True:
            # Process events and update display
            mouse_clicked = self.window.checkMouse()
            if not self.window.running:
                break
            if mouse_clicked:
                return
                
            if debugging:
                start_time = time.time()
                
            # Move each square
            for square in self.created_squares:
                self.moveSquare(square)
                self.window.update()  # Update display after each square moves
                
            if debugging:
                total_time = time.time() - start_time
                print(f"\nDEBUG: Time for all Squares to move: {total_time}")
                
            # Small delay to control movement speed
            time.sleep(0.05)


    def _try_movement(self, square, direction):
        """Helper to attempt movement in a specific direction."""
        cache_key = f"{square.tkinter_id}:{direction}"
        if cache_key in self._collision_cache:
            return self._collision_cache[cache_key]
            
        collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(
            square, self, direction)
            
        self._collision_cache[cache_key] = (collision_detected, selected_direction_coordinates)
        
        if selected_direction_coordinates is None:
            return False, None
            
        return not collision_detected, selected_direction_coordinates

    def _handle_movement(self, square, direction, selected_direction_coordinates=None):
        """Execute movement and collect updates for batch processing."""
        square.selected_direction = direction
        
        # Get updates but don't apply them yet
        geometry_updates, coord_updates = self.moveSquareBody(square, selected_direction_coordinates)
        
        # Add to pending updates
        if geometry_updates:
            self._geometry_updates.append(geometry_updates)
        if coord_updates:
            self._pending_updates.append({
                'square': square,
                'coordinates': coord_updates
            })
        
        return True

    def moveSquare(self, parent_square):
        """Main square movement function.
        
        Handles movement logic including:
        - Initial state setup
        - Direction selection
        - Collision detection and resolution
        - Movement execution
        """
        debugging = False
        if debugging:
            print(f"\nDEBUG: Starting move for Square [{parent_square.square_id}]")
            
        # Initialize movement state
        parent_square.valid_directions = set(self.valid_directions.keys())
        parent_square.directions_already_tried = set()
        parent_square.remaining_directions = set()
        parent_square.selected_direction = None
        
        # Reset square appearance
        parent_square.body.setFill(parent_square.body_color)
        parent_square.body.setOutline(parent_square.outline_color)
        
        # Initialize collision tracking
        collision_chain = []
        colission_chain_coordinates = []
        
        if debugging:
            print(f"DEBUG: Square [{parent_square.square_id}] previous direction: {parent_square.previous_direction}")
        
        '''
        TO-DO:
        Add logic to have larger mass Square "eat" smaller mass Squares
        - Absorbs the smaller square mass and adds it to it's own
        - Adjust fill color to match new mass
        Add logic for every Square to have a %chance to split into smaller Squares
        - % chance of splitting should be higer for larger mass Squares
        '''
        
        # Logic used when Square did not move last cycle
        # if debugging == True:
        #     parent_square.previous_direction = None
        if parent_square.previous_direction == None: 
            self.moveRandomDirection(parent_square)
        elif parent_square.previous_direction != None:
            parent_square.selected_direction = parent_square.previous_direction
            parent_square.directions_already_tried.add(parent_square.selected_direction)
            collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
            # if debugging == True:
            #     # print(f"\nDEBUG: List of valid directions: {self.valid_directions}\n")
            #     print(f"\nDEBUG: Selected direction: {parent_square.selected_direction}\n")
            #     print(f"\nDEBUG: Collision dected: {collision_detected}\n")
            #     print(f"\nDEBUG: Selected direction coordiantes: {selected_direction_coordinates}\n")
            if collision_detected == False:        
                self.moveSquareBody(parent_square, selected_direction_coordinates)  
            elif collision_detected == True and selected_direction_coordinates != None:
                # if debugging == True: 
                    # parent_square.directions_already_tried.add(parent_square.selected_direction)
                    # print(f"Directions already tried are [{directions_already_tried}]")
                # parent_square.body.setOutline("White")
                '''
                Add logic to check for mass for object colliding with
                If mass is higher then continue moving in same direction and add logic to displace lower mass
                Add logic to move lower mass object and also do another collision check for lower mass object
                Add logic to update documents in MongoDB with mass value of Square after it moved
                Unrelated: add logic in Squareverse window for moving diagonally 
                '''
                # if debugging == True:
                #     print(f"\nSelected direction coordinates: {selected_direction_coordinates}")
                #     smaller_square_tk_id = selected_direction_coordinates['tkinter_id']
                #     smaller_square = self.window.find_withtag(smaller_square_tk_id)
                #     print(f"\nSmaller Square object: {smaller_square}\n")
                if parent_square.mass > selected_direction_coordinates['mass']:
                    # smaller_square_tk_id = selected_direction_coordinates['tkinter_id']
                    # smaller_square_object = self.square_objects[smaller_square_tk_id]
                    # collision_chain.append(smaller_square_object)
                    if debugging == True:
                        print(f"\nList of Square object Tkinter IDs: {self.square_objects.keys()}")
                    collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                    
                    # if debugging == True:
                    #     print(f"\nSmaller Square object: {collision_chain[0]}\n")
                    
                    count = 0
                    while True:  
                        collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for chain collision in selected direction
                        colission_chain_coordinates.append(colission_chain_coordinates_temp)
                        if debugging == True:
                            print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                            print(f"\nDEBUG: Square being checked for collision: {parent_square}")
                            print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                            print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                        
                        if collision_detected == False:
                            break
                            
                            # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                            # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                            # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                            # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                            # #
                            # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                            # if smaller_square_object.previous_direction == None:
                            #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                            # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                            # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                            # if debugging == True: 
                            #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                            #     pass
                        elif collision_detected == True and colission_chain_coordinates[count] == None:
                            #work in progress
                            # add logic to delete square as a temporary fix until logic is completed
                            if debugging == True:
                                print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                            self.destroySquare(collision_chain[count])
                            del collision_chain[-1]
                            del colission_chain_coordinates[-1]
                            if debugging == True:
                                print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                            
                            break
                            # pass
                        else:
                            # Need to add logic for comparing mass of Square being checked with Square colliding with
                            if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                if debugging == True:
                                    print(f"\n DEBUG: Chain collision Square has been crushed")
                                self.destroySquare(collision_chain[count])
                                del collision_chain[-1]
                                del colission_chain_coordinates[-1]
                                # if debugging == True:
                                    # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                    # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                break
                            else:
                                collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                count = count + 1
                            
                            # colission_chain_coordinates[count]
                    for collision_square in collision_chain[::-1]: # loops through list from last to first element
                        count = len(colission_chain_coordinates) - 1
                        collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                        collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                        collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                        collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                        #
                        self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                        if collision_square.previous_direction == None:
                            collision_square.previous_direction = parent_square.selected_direction                   
                        # if debugging == True:
                        #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                        self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                        collision_square.body.setOutline(collision_square.outline_color)
                        count = count - 1
                        if debugging == True: 
                            # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                            pass
                     # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                    parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                    parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                    parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                    parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                    #
                    self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                    parent_square.previous_direction = parent_square.selected_direction                    
                    self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                    parent_square.body.setOutline(parent_square.outline_color)
                    # if debugging == True: 
                    #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                else:
                    parent_square.selected_direction = self.valid_directions[parent_square.selected_direction]['i']
                    # if debugging == True: 
                        # print(f"\nDEBUG: Collision detected; trying inverse direction: {parent_square.selected_direction}\n") # DEBUG
                    parent_square.directions_already_tried.add(parent_square.selected_direction)

                    collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                    # parent_square.collision_detection_m, selected_direction_coordinates = parent_square.collision_detection_mongo(self, parent_square.selected_direction)
                    # parent_square.collision_check = parent_square.collisionCheck(self, parent_square.selected_direction)

                    if collision_detected == False:                   
                        # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                        parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                        parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                        parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                        parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                        #
                        self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                        parent_square.previous_direction = parent_square.selected_direction                    
                        self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                        parent_square.body.setOutline(parent_square.outline_color)
                        if debugging == True: 
                            # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                            pass
                    elif collision_detected == True and selected_direction_coordinates != None:
                        if parent_square.mass > selected_direction_coordinates['mass']:
                            collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                            count = 0
                            while True:
                                collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                # if debugging == True:
                                #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                
                                if collision_detected == False:
                                    break
                                    
                                    # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    # #
                                    # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                    # if smaller_square_object.previous_direction == None:
                                    #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                    # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                    # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                    # if debugging == True: 
                                    #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                    #     pass
                                elif collision_detected == True and colission_chain_coordinates[count] == None:
                                    #work in progress
                                    # add logic to delete square as a temporary fix until logic is completed
                                    if debugging == True:
                                        print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                    self.destroySquare(collision_chain[count])
                                    del collision_chain[-1]
                                    del colission_chain_coordinates[-1]
                                    if debugging == True:
                                        print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                        print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                    
                                    break
                                    # pass
                                else:
                                    # Need to add logic for comparing mass of Square being checked with Square colliding with
                                    if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                        if debugging == True:
                                            print(f"\n DEBUG: Chain collision Square has been crushed")
                                        self.destroySquare(collision_chain[count])
                                        del collision_chain[-1]
                                        del colission_chain_coordinates[-1]
                                        # if debugging == True:
                                            # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                            # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                        break
                                    else:
                                        collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                        count = count + 1
                                    
                                    # colission_chain_coordinates[count]
                            for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                count = len(colission_chain_coordinates) - 1
                                collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                #
                                self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                if collision_square.previous_direction == None:
                                    collision_square.previous_direction = parent_square.selected_direction                   
                                # if debugging == True:
                                #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                collision_square.body.setOutline(collision_square.outline_color)
                                count = count - 1
                                if debugging == True: 
                                    # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                    pass
                            # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                            parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                            parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                            parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                            parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                            #
                            self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                            parent_square.previous_direction = parent_square.selected_direction                    
                            self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                            parent_square.body.setOutline(parent_square.outline_color)
                            if debugging == True: 
                                # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                pass
                        else:
                            remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                            parent_square.selected_direction = choice(list(remaining_directions))
                            parent_square.directions_already_tried.add(parent_square.selected_direction)
                            collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                            
                            if collision_detected == False:                   
                                # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                #
                                self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                parent_square.previous_direction = parent_square.selected_direction                    
                                self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                parent_square.body.setOutline(parent_square.outline_color)
                                if debugging == True: 
                                    # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                    pass
                            elif collision_detected == True and selected_direction_coordinates != None:
                                if parent_square.mass > selected_direction_coordinates['mass']:
                                    collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                    count = 0
                                    while True:
                                        collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                        colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                        # if debugging == True:
                                        #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                        #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                        #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                        #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                        
                                        if collision_detected == False:
                                            break
                                            
                                            # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                            # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                            # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                            # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                            # #
                                            # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                            # if smaller_square_object.previous_direction == None:
                                            #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                            # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                            # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                            # if debugging == True: 
                                            #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            #     pass
                                        elif collision_detected == True and colission_chain_coordinates[count] == None:
                                            #work in progress
                                            # add logic to delete square as a temporary fix until logic is completed
                                            if debugging == True:
                                                print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                            self.destroySquare(collision_chain[count])
                                            del collision_chain[-1]
                                            del colission_chain_coordinates[-1]
                                            if debugging == True:
                                                print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                            
                                            break
                                            # pass
                                        else:
                                            # Need to add logic for comparing mass of Square being checked with Square colliding with
                                            if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collision Square has been crushed")
                                                self.destroySquare(collision_chain[count])
                                                del collision_chain[-1]
                                                del colission_chain_coordinates[-1]
                                                # if debugging == True:
                                                    # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                    # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                break
                                            else:
                                                collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                                count = count + 1
                                            
                                            # colission_chain_coordinates[count]
                                    for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                        count = len(colission_chain_coordinates) - 1
                                        collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        #
                                        self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                        if collision_square.previous_direction == None:
                                            collision_square.previous_direction = parent_square.selected_direction                   
                                        # if debugging == True:
                                        #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                        self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                        collision_square.body.setOutline(collision_square.outline_color)
                                        count = count - 1
                                        if debugging == True: 
                                            # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            pass
                                    # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                    parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    #
                                    self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                    parent_square.previous_direction = parent_square.selected_direction                    
                                    self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                    parent_square.body.setOutline(parent_square.outline_color)
                                    if debugging == True: 
                                        # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        pass
                                else:
                                    remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                                    parent_square.selected_direction = choice(list(remaining_directions))
                                    parent_square.directions_already_tried.add(parent_square.selected_direction)
                                    collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                                
                                    if collision_detected == False:                   
                                        # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                        parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        #
                                        self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                        parent_square.previous_direction = parent_square.selected_direction                    
                                        self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                        parent_square.body.setOutline(parent_square.outline_color)
                                        if debugging == True: 
                                            # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            pass
                                    elif collision_detected == True and selected_direction_coordinates != None:
                                        if parent_square.mass > selected_direction_coordinates['mass']:
                                            collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                            count = 0
                                            while True:
                                                collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                                colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                                # if debugging == True:
                                                #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                                #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                                #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                                #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                                
                                                if collision_detected == False:
                                                    break
                                                    
                                                    # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                                    # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                                    # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                                    # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                                    # #
                                                    # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                                    # if smaller_square_object.previous_direction == None:
                                                    #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                                    # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                                    # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                                    # if debugging == True: 
                                                    #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                                    #     pass
                                                elif collision_detected == True and colission_chain_coordinates[count] == None:
                                                    #work in progress
                                                    # add logic to delete square as a temporary fix until logic is completed
                                                    if debugging == True:
                                                        print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                                    self.destroySquare(collision_chain[count])
                                                    del collision_chain[-1]
                                                    del colission_chain_coordinates[-1]
                                                    if debugging == True:
                                                        print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                        print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                    
                                                    break
                                                    # pass
                                                else:
                                                    # Need to add logic for comparing mass of Square being checked with Square colliding with
                                                    if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                                        if debugging == True:
                                                            print(f"\n DEBUG: Chain collision Square has been crushed")
                                                        self.destroySquare(collision_chain[count])
                                                        del collision_chain[-1]
                                                        del colission_chain_coordinates[-1]
                                                        # if debugging == True:
                                                            # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                            # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                        break
                                                    else:
                                                        collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                                        count = count + 1
                                                    
                                                    # colission_chain_coordinates[count]
                                            for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                                count = len(colission_chain_coordinates) - 1
                                                collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                                collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                                collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                                collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                                #
                                                self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                                if collision_square.previous_direction == None:
                                                    collision_square.previous_direction = parent_square.selected_direction                   
                                                # if debugging == True:
                                                #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                                self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                                collision_square.body.setOutline(collision_square.outline_color)
                                                count = count - 1
                                                if debugging == True: 
                                                    # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                                    pass
                                            # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                            parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                            parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                            parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                            parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                            #
                                            self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                            parent_square.previous_direction = parent_square.selected_direction                    
                                            self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                            parent_square.body.setOutline(parent_square.outline_color)
                                            if debugging == True: 
                                                # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                                pass
                                        else:
                                            if debugging == True: 
                                                print(f"\nDEBUG: There are no move valid directions remaining")
                                                print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                            self.destroySquare(parent_square)
                                    elif collision_detected == True and selected_direction_coordinates == None:
                                        # parent_square.body.setOutline("White")
                                        if debugging == True:
                                            print(f"\nDEBUG: There are no move valid directions remaining")
                            elif collision_detected == True and selected_direction_coordinates == None:
                                remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                                parent_square.selected_direction = choice(list(remaining_directions))
                                parent_square.directions_already_tried.add(parent_square.selected_direction)
                                collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                            
                                if collision_detected == False:                   
                                    # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                    parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    #
                                    self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                    parent_square.previous_direction = parent_square.selected_direction                    
                                    self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                    parent_square.body.setOutline(parent_square.outline_color)
                                    if debugging == True: 
                                        # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        pass
                                elif collision_detected == True and selected_direction_coordinates != None:
                                    if parent_square.mass > selected_direction_coordinates['mass']:
                                        collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                        count = 0
                                        while True:
                                            collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                            colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                            # if debugging == True:
                                            #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                            #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                            #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                            #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                            
                                            if collision_detected == False:
                                                break
                                                
                                                # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                                # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                                # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                                # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                                # #
                                                # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                                # if smaller_square_object.previous_direction == None:
                                                #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                                # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                                # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                                # if debugging == True: 
                                                #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                                #     pass
                                            elif collision_detected == True and colission_chain_coordinates[count] == None:
                                                #work in progress
                                                # add logic to delete square as a temporary fix until logic is completed
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                                self.destroySquare(collision_chain[count])
                                                del collision_chain[-1]
                                                del colission_chain_coordinates[-1]
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                    print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                
                                                break
                                                # pass
                                            else:
                                                # Need to add logic for comparing mass of Square being checked with Square colliding with
                                                if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                                    if debugging == True:
                                                        print(f"\n DEBUG: Chain collision Square has been crushed")
                                                    self.destroySquare(collision_chain[count])
                                                    del collision_chain[-1]
                                                    del colission_chain_coordinates[-1]
                                                    # if debugging == True:
                                                        # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                        # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                    break
                                                else:
                                                    collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                                    count = count + 1
                                                
                                                # colission_chain_coordinates[count]
                                        for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                            count = len(colission_chain_coordinates) - 1
                                            collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                            collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                            collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                            collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                            #
                                            self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                            if collision_square.previous_direction == None:
                                                collision_square.previous_direction = parent_square.selected_direction                   
                                            # if debugging == True:
                                            #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                            self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                            collision_square.body.setOutline(collision_square.outline_color)
                                            count = count - 1
                                            if debugging == True: 
                                                # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                                pass
                                        # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                        parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        #
                                        self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                        parent_square.previous_direction = parent_square.selected_direction                    
                                        self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                        parent_square.body.setOutline(parent_square.outline_color)
                                        if debugging == True: 
                                            # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            pass
                                    else:
                                        if debugging == True: 
                                            print(f"\nDEBUG: There are no move valid directions remaining")
                                            print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                        self.destroySquare(parent_square)
                                elif collision_detected == True and selected_direction_coordinates == None:
                                    if debugging == True: 
                                        print(f"\nDEBUG: There are no move valid directions remaining")
                                        print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                    self.destroySquare(parent_square)
                    elif collision_detected == True and selected_direction_coordinates == None:
                        remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                        parent_square.selected_direction = choice(list(remaining_directions))
                        parent_square.directions_already_tried.add(parent_square.selected_direction)
                        collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                        
                        if collision_detected == False:                   
                            # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                            parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                            parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                            parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                            parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                            #
                            self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                            parent_square.previous_direction = parent_square.selected_direction                    
                            self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                            parent_square.body.setOutline(parent_square.outline_color)
                            if debugging == True: 
                                # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                pass
                        elif collision_detected == True and selected_direction_coordinates != None:
                            if parent_square.mass > selected_direction_coordinates['mass']:
                                collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                count = 0
                                while True:
                                    collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                    colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                    # if debugging == True:
                                    #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                    #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                    #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                    #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                    
                                    if collision_detected == False:
                                        break
                                        
                                        # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        # #
                                        # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                        # if smaller_square_object.previous_direction == None:
                                        #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                        # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                        # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                        # if debugging == True: 
                                        #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        #     pass
                                    elif collision_detected == True and colission_chain_coordinates[count] == None:
                                        #work in progress
                                        # add logic to delete square as a temporary fix until logic is completed
                                        if debugging == True:
                                            print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                        self.destroySquare(collision_chain[count])
                                        del collision_chain[-1]
                                        del colission_chain_coordinates[-1]
                                        if debugging == True:
                                            print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                            print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                        
                                        break
                                        # pass
                                    else:
                                        # Need to add logic for comparing mass of Square being checked with Square colliding with
                                        if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                            if debugging == True:
                                                print(f"\n DEBUG: Chain collision Square has been crushed")
                                            self.destroySquare(collision_chain[count])
                                            del collision_chain[-1]
                                            del colission_chain_coordinates[-1]
                                            # if debugging == True:
                                                # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                            break
                                        else:
                                            collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                            count = count + 1
                                        
                                        # colission_chain_coordinates[count]
                                for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                    count = len(colission_chain_coordinates) - 1
                                    collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    #
                                    self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                    if collision_square.previous_direction == None:
                                        collision_square.previous_direction = parent_square.selected_direction                   
                                    # if debugging == True:
                                    #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                    self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                    collision_square.body.setOutline(collision_square.outline_color)
                                    count = count - 1
                                    if debugging == True: 
                                        # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        pass
                                # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                #
                                self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                parent_square.previous_direction = parent_square.selected_direction                    
                                self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                parent_square.body.setOutline(parent_square.outline_color)
                                if debugging == True: 
                                    # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                    pass
                            else:
                                remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                                parent_square.selected_direction = choice(list(remaining_directions))
                                parent_square.directions_already_tried.add(parent_square.selected_direction)
                                collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                            
                                if collision_detected == False:                   
                                    # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                    parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    #
                                    self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                    parent_square.previous_direction = parent_square.selected_direction                    
                                    self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                    parent_square.body.setOutline(parent_square.outline_color)
                                    if debugging == True: 
                                        # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        pass
                                elif collision_detected == True and selected_direction_coordinates != None:
                                    if parent_square.mass > selected_direction_coordinates['mass']:
                                        collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                        count = 0
                                        while True:
                                            collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                            colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                            # if debugging == True:
                                            #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                            #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                            #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                            #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                            
                                            if collision_detected == False:
                                                break
                                                
                                                # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                                # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                                # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                                # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                                # #
                                                # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                                # if smaller_square_object.previous_direction == None:
                                                #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                                # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                                # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                                # if debugging == True: 
                                                #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                                #     pass
                                            elif collision_detected == True and colission_chain_coordinates[count] == None:
                                                #work in progress
                                                # add logic to delete square as a temporary fix until logic is completed
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                                self.destroySquare(collision_chain[count])
                                                del collision_chain[-1]
                                                del colission_chain_coordinates[-1]
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                    print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                
                                                break
                                                # pass
                                            else:
                                                # Need to add logic for comparing mass of Square being checked with Square colliding with
                                                if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                                    if debugging == True:
                                                        print(f"\n DEBUG: Chain collision Square has been crushed")
                                                        self.destroySquare(collision_chain[count])
                                                        del collision_chain[-1]
                                                        del colission_chain_coordinates[-1]
                                                        # if debugging == True:
                                                            # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                            # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                        break
                                                else:
                                                    collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                                    count = count + 1
                                                
                                                # colission_chain_coordinates[count]
                                        for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                            count = len(colission_chain_coordinates) - 1
                                            collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                            collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                            collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                            collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                            #
                                            self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                            if collision_square.previous_direction == None:
                                                collision_square.previous_direction = parent_square.selected_direction                   
                                            # if debugging == True:
                                            #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                            self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                            collision_square.body.setOutline(collision_square.outline_color)
                                            count = count - 1
                                            if debugging == True: 
                                                # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                                pass
                                        # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                        parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        #
                                        self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                        parent_square.previous_direction = parent_square.selected_direction                    
                                        self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                        parent_square.body.setOutline(parent_square.outline_color)
                                        if debugging == True: 
                                            # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            pass
                                    else:
                                        if debugging == True: 
                                            print(f"\nDEBUG: There are no move valid directions remaining")
                                            print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                        self.destroySquare(parent_square)
                                elif collision_detected == True and selected_direction_coordinates == None:
                                    if debugging == True: 
                                        print(f"\nDEBUG: There are no move valid directions remaining")
                                        print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                    self.destroySquare(parent_square)
                        elif collision_detected == True and selected_direction_coordinates == None:
                            remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                            parent_square.selected_direction = choice(list(remaining_directions))
                            parent_square.directions_already_tried.add(parent_square.selected_direction)
                            collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                        
                            if collision_detected == False:                   
                                # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                #
                                self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                parent_square.previous_direction = parent_square.selected_direction                    
                                self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                parent_square.body.setOutline(parent_square.outline_color)
                                if debugging == True: 
                                    # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                    pass
                            elif collision_detected == True and selected_direction_coordinates != None:
                                if parent_square.mass > selected_direction_coordinates['mass']:
                                    collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                    count = 0
                                    while True:
                                        collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                        colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                        # if debugging == True:
                                        #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                        #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                        #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                        #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                        
                                        if collision_detected == False:
                                            break
                                            
                                            # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                            # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                            # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                            # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                            # #
                                            # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                            # if smaller_square_object.previous_direction == None:
                                            #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                            # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                            # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                            # if debugging == True: 
                                            #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            #     pass
                                        elif collision_detected == True and colission_chain_coordinates[count] == None:
                                            #work in progress
                                            # add logic to delete square as a temporary fix until logic is completed
                                            if debugging == True:
                                                print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                            self.destroySquare(collision_chain[count])
                                            del collision_chain[-1]
                                            del colission_chain_coordinates[-1]
                                            if debugging == True:
                                                print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                            
                                            break
                                            # pass
                                        else:
                                            # Need to add logic for comparing mass of Square being checked with Square colliding with
                                            if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collision Square has been crushed")
                                                self.destroySquare(collision_chain[count])
                                                del collision_chain[-1]
                                                del colission_chain_coordinates[-1]
                                                # if debugging == True:
                                                    # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                    # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                break
                                            else:
                                                collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                                count = count + 1
                                            
                                            # colission_chain_coordinates[count]
                                    for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                        count = len(colission_chain_coordinates) - 1
                                        collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        #
                                        self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                        if collision_square.previous_direction == None:
                                            collision_square.previous_direction = parent_square.selected_direction                   
                                        # if debugging == True:
                                        #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                        self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                        collision_square.body.setOutline(collision_square.outline_color)
                                        count = count - 1
                                        if debugging == True: 
                                            # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            pass
                                    # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                    parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    #
                                    self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                    parent_square.previous_direction = parent_square.selected_direction                    
                                    self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                    parent_square.body.setOutline(parent_square.outline_color)
                                    if debugging == True: 
                                        # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        pass
                                else:
                                        if debugging == True: 
                                            print(f"\nDEBUG: There are no move valid directions remaining")
                                            print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                        self.destroySquare(parent_square)
                            elif collision_detected == True and selected_direction_coordinates == None:
                                if debugging == True: 
                                    print(f"\nDEBUG: There are no move valid directions remaining")
                                    print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                self.destroySquare(parent_square)
            elif collision_detected == True and selected_direction_coordinates == None:
                parent_square.selected_direction = self.valid_directions[parent_square.selected_direction]['i']
                # if debugging == True: 
                    # print(f"\nDEBUG: Collision detected; trying inverse direction: {parent_square.selected_direction}\n") # DEBUG
                parent_square.directions_already_tried.add(parent_square.selected_direction)

                collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                # parent_square.collision_detection_m, selected_direction_coordinates = parent_square.collision_detection_mongo(self, parent_square.selected_direction)
                # parent_square.collision_check = parent_square.collisionCheck(self, parent_square.selected_direction)

                if collision_detected == False:                   
                    self.moveSquareBody(parent_square, selected_direction_coordinates)
                elif collision_detected == True and selected_direction_coordinates != None:
                    if parent_square.mass > selected_direction_coordinates['mass']:
                        collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                        count = 0
                        while True:
                            collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                            colission_chain_coordinates.append(colission_chain_coordinates_temp)
                            # if debugging == True:
                            #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                            #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                            #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                            #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                            
                            if collision_detected == False:
                                break
                                
                                # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                # #
                                # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                # if smaller_square_object.previous_direction == None:
                                #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                # if debugging == True: 
                                #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                #     pass
                            elif collision_detected == True and colission_chain_coordinates[count] == None:
                                #work in progress
                                # add logic to delete square as a temporary fix until logic is completed
                                if debugging == True:
                                    print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                self.destroySquare(collision_chain[count])
                                del collision_chain[-1]
                                del colission_chain_coordinates[-1]
                                if debugging == True:
                                    print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                    print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                
                                break
                                # pass
                            else:
                                # Need to add logic for comparing mass of Square being checked with Square colliding with
                                if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                    if debugging == True:
                                        print(f"\n DEBUG: Chain collision Square has been crushed")
                                    self.destroySquare(collision_chain[count])
                                    del collision_chain[-1]
                                    del colission_chain_coordinates[-1]
                                    # if debugging == True:
                                        # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                        # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                    break
                                else:
                                    collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                    count = count + 1
                                
                                # colission_chain_coordinates[count]
                        for collision_square in collision_chain[::-1]: # loops through list from last to first element
                            count = len(colission_chain_coordinates) - 1
                            self.moveSquareBody(collision_square, colission_chain_coordinates[count])
                            # collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                            # collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                            # collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                            # collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                            # #
                            # self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                            # if collision_square.previous_direction == None:
                            #     collision_square.previous_direction = parent_square.selected_direction                   
                            # # if debugging == True:
                            # #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                            # self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                            # collision_square.body.setOutline(collision_square.outline_color)
                            # count = count - 1
                            # if debugging == True: 
                            #     # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                            #     pass
                        self.moveSquareBody(parent_square, selected_direction_coordinates)
                    else:
                        remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                        parent_square.selected_direction = choice(list(remaining_directions))
                        parent_square.directions_already_tried.add(parent_square.selected_direction)
                        collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                        
                        if collision_detected == False:                   
                            # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                            parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                            parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                            parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                            parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                            #
                            self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                            parent_square.previous_direction = parent_square.selected_direction                    
                            self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                            parent_square.body.setOutline(parent_square.outline_color)
                            if debugging == True: 
                                # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                pass
                        elif collision_detected == True and selected_direction_coordinates != None:
                            if parent_square.mass > selected_direction_coordinates['mass']:
                                collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                count = 0
                                while True:
                                    collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                    colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                    # if debugging == True:
                                    #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                    #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                    #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                    #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                    
                                    if collision_detected == False:
                                        break
                                        
                                        # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        # #
                                        # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                        # if smaller_square_object.previous_direction == None:
                                        #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                        # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                        # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                        # if debugging == True: 
                                        #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        #     pass
                                    elif collision_detected == True and colission_chain_coordinates[count] == None:
                                        #work in progress
                                        # add logic to delete square as a temporary fix until logic is completed
                                        if debugging == True:
                                            print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                        self.destroySquare(collision_chain[count])
                                        del collision_chain[-1]
                                        del colission_chain_coordinates[-1]
                                        if debugging == True:
                                            print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                            print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                        
                                        break
                                        # pass
                                    else:
                                        # Need to add logic for comparing mass of Square being checked with Square colliding with
                                        if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                            if debugging == True:
                                                print(f"\n DEBUG: Chain collision Square has been crushed")
                                            self.destroySquare(collision_chain[count])
                                            del collision_chain[-1]
                                            del colission_chain_coordinates[-1]
                                            # if debugging == True:
                                                # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                            break
                                        else:
                                            collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                            count = count + 1
                                        
                                        # colission_chain_coordinates[count]
                                for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                    count = len(colission_chain_coordinates) - 1
                                    collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    #
                                    self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                    if collision_square.previous_direction == None:
                                        collision_square.previous_direction = parent_square.selected_direction                   
                                    # if debugging == True:
                                    #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                    self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                    collision_square.body.setOutline(collision_square.outline_color)
                                    count = count - 1
                                    if debugging == True: 
                                        # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        pass
                                # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                #
                                self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                parent_square.previous_direction = parent_square.selected_direction                    
                                self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                parent_square.body.setOutline(parent_square.outline_color)
                                if debugging == True: 
                                    # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                    pass
                            else:
                                remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                                parent_square.selected_direction = choice(list(remaining_directions))
                                parent_square.directions_already_tried.add(parent_square.selected_direction)
                                collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                            
                                if collision_detected == False:                   
                                    # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                    parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    #
                                    self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                    parent_square.previous_direction = parent_square.selected_direction                    
                                    self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                    parent_square.body.setOutline(parent_square.outline_color)
                                    if debugging == True: 
                                        # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        pass
                                elif collision_detected == True and selected_direction_coordinates != None:
                                    if parent_square.mass > selected_direction_coordinates['mass']:
                                        collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                        count = 0
                                        while True:
                                            collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                            colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                            # if debugging == True:
                                            #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                            #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                            #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                            #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                            
                                            if collision_detected == False:
                                                break
                                                
                                                # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                                # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                                # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                                # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                                # #
                                                # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                                # if smaller_square_object.previous_direction == None:
                                                #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                                # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                                # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                                # if debugging == True: 
                                                #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                                #     pass
                                            elif collision_detected == True and colission_chain_coordinates[count] == None:
                                                #work in progress
                                                # add logic to delete square as a temporary fix until logic is completed
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                                self.destroySquare(collision_chain[count])
                                                del collision_chain[-1]
                                                del colission_chain_coordinates[-1]
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                    print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                
                                                break
                                                # pass
                                            else:
                                                # Need to add logic for comparing mass of Square being checked with Square colliding with
                                                if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                                    if debugging == True:
                                                        print(f"\n DEBUG: Chain collision Square has been crushed")
                                                    self.destroySquare(collision_chain[count])
                                                    del collision_chain[-1]
                                                    del colission_chain_coordinates[-1]
                                                    # if debugging == True:
                                                        # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                        # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                    break
                                                else:
                                                    collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                                    count = count + 1
                                                
                                                # colission_chain_coordinates[count]
                                        for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                            count = len(colission_chain_coordinates) - 1
                                            collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                            collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                            collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                            collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                            #
                                            self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                            if collision_square.previous_direction == None:
                                                collision_square.previous_direction = parent_square.selected_direction                   
                                            # if debugging == True:
                                            #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                            self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                            collision_square.body.setOutline(collision_square.outline_color)
                                            count = count - 1
                                            if debugging == True: 
                                                # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                                pass
                                        # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                        parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        #
                                        self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                        parent_square.previous_direction = parent_square.selected_direction                    
                                        self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                        parent_square.body.setOutline(parent_square.outline_color)
                                        if debugging == True: 
                                            # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            pass
                                    else:
                                        if debugging == True: 
                                            print(f"\nDEBUG: There are no move valid directions remaining")
                                            print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                        self.destroySquare(parent_square)
                                elif collision_detected == True and selected_direction_coordinates == None:
                                    # parent_square.body.setOutline("White")
                                    if debugging == True:
                                        print(f"\nDEBUG: There are no move valid directions remaining")
                        elif collision_detected == True and selected_direction_coordinates == None:
                            remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                            parent_square.selected_direction = choice(list(remaining_directions))
                            parent_square.directions_already_tried.add(parent_square.selected_direction)
                            collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                        
                            if collision_detected == False:                   
                                # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                #
                                self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                parent_square.previous_direction = parent_square.selected_direction                    
                                self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                parent_square.body.setOutline(parent_square.outline_color)
                                if debugging == True: 
                                    # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                    pass
                            elif collision_detected == True and selected_direction_coordinates != None:
                                if parent_square.mass > selected_direction_coordinates['mass']:
                                    collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                    count = 0
                                    while True:
                                        collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                        colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                        # if debugging == True:
                                        #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                        #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                        #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                        #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                        
                                        if collision_detected == False:
                                            break
                                            
                                            # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                            # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                            # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                            # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                            # #
                                            # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                            # if smaller_square_object.previous_direction == None:
                                            #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                            # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                            # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                            # if debugging == True: 
                                            #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            #     pass
                                        elif collision_detected == True and colission_chain_coordinates[count] == None:
                                            #work in progress
                                            # add logic to delete square as a temporary fix until logic is completed
                                            if debugging == True:
                                                print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                            self.destroySquare(collision_chain[count])
                                            del collision_chain[-1]
                                            del colission_chain_coordinates[-1]
                                            if debugging == True:
                                                print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                            
                                            break
                                            # pass
                                        else:
                                            # Need to add logic for comparing mass of Square being checked with Square colliding with
                                            if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collision Square has been crushed")
                                                self.destroySquare(collision_chain[count])
                                                del collision_chain[-1]
                                                del colission_chain_coordinates[-1]
                                                # if debugging == True:
                                                    # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                    # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                break
                                            else:
                                                collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                                count = count + 1
                                            
                                            # colission_chain_coordinates[count]
                                    for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                        count = len(colission_chain_coordinates) - 1
                                        collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        #
                                        self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                        if collision_square.previous_direction == None:
                                            collision_square.previous_direction = parent_square.selected_direction                   
                                        # if debugging == True:
                                        #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                        self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                        collision_square.body.setOutline(collision_square.outline_color)
                                        count = count - 1
                                        if debugging == True: 
                                            # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            pass
                                    # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                    parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    #
                                    self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                    parent_square.previous_direction = parent_square.selected_direction                    
                                    self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                    parent_square.body.setOutline(parent_square.outline_color)
                                    if debugging == True: 
                                        # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        pass
                                else:
                                    if debugging == True: 
                                        print(f"\nDEBUG: There are no move valid directions remaining")
                                        print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                    self.destroySquare(parent_square)
                            elif collision_detected == True and selected_direction_coordinates == None:
                                if debugging == True: 
                                    print(f"\nDEBUG: There are no move valid directions remaining")
                                    print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                self.destroySquare(parent_square)
                # LEFT OFF HERE;
                
                elif collision_detected == True and selected_direction_coordinates == None:
                    remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                    parent_square.selected_direction = choice(list(remaining_directions))
                    parent_square.directions_already_tried.add(parent_square.selected_direction)
                    collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                    
                    if collision_detected == False:                   
                        self.moveSquareBody(parent_square, selected_direction_coordinates)
                    elif collision_detected == True and selected_direction_coordinates != None:
                        if parent_square.mass > selected_direction_coordinates['mass']:
                            collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                            count = 0
                            while True:
                                collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                # if debugging == True:
                                #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                
                                if collision_detected == False:
                                    break
                                    
                                    # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    # #
                                    # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                    # if smaller_square_object.previous_direction == None:
                                    #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                    # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                    # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                    # if debugging == True: 
                                    #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                    #     pass
                                elif collision_detected == True and colission_chain_coordinates[count] == None:
                                    #work in progress
                                    # add logic to delete square as a temporary fix until logic is completed
                                    if debugging == True:
                                        print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                    self.destroySquare(collision_chain[count])
                                    del collision_chain[-1]
                                    del colission_chain_coordinates[-1]
                                    if debugging == True:
                                        print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                        print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                    
                                    break
                                    # pass
                                else:
                                    # Need to add logic for comparing mass of Square being checked with Square colliding with
                                    if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                        if debugging == True:
                                            print(f"\n DEBUG: Chain collision Square has been crushed")
                                        self.destroySquare(collision_chain[count])
                                        del collision_chain[-1]
                                        del colission_chain_coordinates[-1]
                                        # if debugging == True:
                                            # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                            # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                        break
                                    else:
                                        collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                        count = count + 1
                                    
                                    # colission_chain_coordinates[count]
                            for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                count = len(colission_chain_coordinates) - 1
                                collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                #
                                self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                if collision_square.previous_direction == None:
                                    collision_square.previous_direction = parent_square.selected_direction                   
                                # if debugging == True:
                                #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                collision_square.body.setOutline(collision_square.outline_color)
                                count = count - 1
                                if debugging == True: 
                                    # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                    pass
                            # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                            parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                            parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                            parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                            parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                            #
                            self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                            parent_square.previous_direction = parent_square.selected_direction                    
                            self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                            parent_square.body.setOutline(parent_square.outline_color)
                            if debugging == True: 
                                # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                pass
                        else:
                            remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                            parent_square.selected_direction = choice(list(remaining_directions))
                            parent_square.directions_already_tried.add(parent_square.selected_direction)
                            collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                        
                            if collision_detected == False:                   
                                # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                #
                                self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                parent_square.previous_direction = parent_square.selected_direction                    
                                self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                parent_square.body.setOutline(parent_square.outline_color)
                                if debugging == True: 
                                    # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                    pass
                            elif collision_detected == True and selected_direction_coordinates != None:
                                if parent_square.mass > selected_direction_coordinates['mass']:
                                    collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                    count = 0
                                    while True:
                                        collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                        colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                        # if debugging == True:
                                        #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                        #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                        #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                        #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                        
                                        if collision_detected == False:
                                            break
                                            
                                            # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                            # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                            # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                            # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                            # #
                                            # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                            # if smaller_square_object.previous_direction == None:
                                            #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                            # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                            # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                            # if debugging == True: 
                                            #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            #     pass
                                        elif collision_detected == True and colission_chain_coordinates[count] == None:
                                            #work in progress
                                            # add logic to delete square as a temporary fix until logic is completed
                                            if debugging == True:
                                                print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                            self.destroySquare(collision_chain[count])
                                            del collision_chain[-1]
                                            del colission_chain_coordinates[-1]
                                            if debugging == True:
                                                print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                            
                                            break
                                            # pass
                                        else:
                                            # Need to add logic for comparing mass of Square being checked with Square colliding with
                                            if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collision Square has been crushed")
                                                    self.destroySquare(collision_chain[count])
                                                    del collision_chain[-1]
                                                    del colission_chain_coordinates[-1]
                                                    # if debugging == True:
                                                        # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                        # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                    break
                                            else:
                                                collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                                count = count + 1
                                            
                                            # colission_chain_coordinates[count]
                                    for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                        count = len(colission_chain_coordinates) - 1
                                        collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        #
                                        self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                        if collision_square.previous_direction == None:
                                            collision_square.previous_direction = parent_square.selected_direction                   
                                        # if debugging == True:
                                        #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                        self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                        collision_square.body.setOutline(collision_square.outline_color)
                                        count = count - 1
                                        if debugging == True: 
                                            # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            pass
                                    # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                    parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    #
                                    self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                    parent_square.previous_direction = parent_square.selected_direction                    
                                    self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                    parent_square.body.setOutline(parent_square.outline_color)
                                    if debugging == True: 
                                        # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        pass
                                else:
                                    if debugging == True: 
                                        print(f"\nDEBUG: There are no move valid directions remaining")
                                        print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                    self.destroySquare(parent_square)
                            elif collision_detected == True and selected_direction_coordinates == None:
                                remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                                parent_square.selected_direction = choice(list(remaining_directions))
                                parent_square.directions_already_tried.add(parent_square.selected_direction)
                                collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                            
                                if collision_detected == False:                   
                                    # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                    parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    #
                                    self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                    parent_square.previous_direction = parent_square.selected_direction                    
                                    self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                    parent_square.body.setOutline(parent_square.outline_color)
                                    if debugging == True: 
                                        # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        pass
                                elif collision_detected == True and selected_direction_coordinates != None:
                                    if parent_square.mass > selected_direction_coordinates['mass']:
                                        collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                        count = 0
                                        while True:
                                            collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                            colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                            # if debugging == True:
                                            #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                            #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                            #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                            #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                            
                                            if collision_detected == False:
                                                break
                                                
                                                # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                                # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                                # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                                # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                                # #
                                                # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                                # if smaller_square_object.previous_direction == None:
                                                #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                                # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                                # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                                # if debugging == True: 
                                                #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                                #     pass
                                            elif collision_detected == True and colission_chain_coordinates[count] == None:
                                                #work in progress
                                                # add logic to delete square as a temporary fix until logic is completed
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                                self.destroySquare(collision_chain[count])
                                                del collision_chain[-1]
                                                del colission_chain_coordinates[-1]
                                                if debugging == True:
                                                    print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                    print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                
                                                break
                                                # pass
                                            else:
                                                # Need to add logic for comparing mass of Square being checked with Square colliding with
                                                if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                                    if debugging == True:
                                                        print(f"\n DEBUG: Chain collision Square has been crushed")
                                                    self.destroySquare(collision_chain[count])
                                                    del collision_chain[-1]
                                                    del colission_chain_coordinates[-1]
                                                    # if debugging == True:
                                                        # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                        # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                                    break
                                                else:
                                                    collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                                    count = count + 1
                                                
                                                # colission_chain_coordinates[count]
                                        for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                            count = len(colission_chain_coordinates) - 1
                                            collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                            collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                            collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                            collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                            #
                                            self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                            if collision_square.previous_direction == None:
                                                collision_square.previous_direction = parent_square.selected_direction                   
                                            # if debugging == True:
                                            #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                            self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                            collision_square.body.setOutline(collision_square.outline_color)
                                            count = count - 1
                                            if debugging == True: 
                                                # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                                pass
                                        # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                        parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        #
                                        self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                        parent_square.previous_direction = parent_square.selected_direction                    
                                        self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                        parent_square.body.setOutline(parent_square.outline_color)
                                        if debugging == True: 
                                            # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                            pass
                                    else:
                                            if debugging == True: 
                                                print(f"\nDEBUG: There are no move valid directions remaining")
                                                print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                            self.destroySquare(parent_square)
                                elif collision_detected == True and selected_direction_coordinates == None:
                                    if debugging == True: 
                                        print(f"\nDEBUG: There are no move valid directions remaining")
                                        print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                    self.destroySquare(parent_square)  
                    elif collision_detected == True and selected_direction_coordinates == None:
                        remaining_directions = parent_square.valid_directions.difference(parent_square.directions_already_tried)
                        parent_square.selected_direction = choice(list(remaining_directions))
                        parent_square.directions_already_tried.add(parent_square.selected_direction)
                        collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(parent_square, self, parent_square.selected_direction) # checks for collision in selected direction
                    
                        if collision_detected == False:                   
                            self.moveSquareBody(parent_square, selected_direction_coordinates)
                        elif collision_detected == True and selected_direction_coordinates != None:
                            if parent_square.mass > selected_direction_coordinates['mass']:
                                collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
                                count = 0
                                while True:
                                    collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, parent_square.selected_direction) # checks for collision in selected direction
                                    colission_chain_coordinates.append(colission_chain_coordinates_temp)
                                    # if debugging == True:
                                    #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                                    #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                                    #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                                    #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                    
                                    if collision_detected == False:
                                        break
                                        
                                        # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                        # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                        # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                        # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                        # #
                                        # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                        # if smaller_square_object.previous_direction == None:
                                        #     smaller_square_object.previous_direction = parent_square.selected_direction                   
                                        # self.mongo_client.update_parent_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                                        # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                                        # if debugging == True: 
                                        #     # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        #     pass
                                    elif collision_detected == True and colission_chain_coordinates[count] == None:
                                        #work in progress
                                        # add logic to delete square as a temporary fix until logic is completed
                                        if debugging == True:
                                            print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                                        self.destroySquare(collision_chain[count])
                                        del collision_chain[-1]
                                        del colission_chain_coordinates[-1]
                                        if debugging == True:
                                            print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                            print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                        
                                        break
                                        # pass
                                    else:
                                        # Need to add logic for comparing mass of Square being checked with Square colliding with
                                        if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                                            if debugging == True:
                                                print(f"\n DEBUG: Chain collision Square has been crushed")
                                            self.destroySquare(collision_chain[count])
                                            del collision_chain[-1]
                                            del colission_chain_coordinates[-1]
                                            # if debugging == True:
                                                # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                                                # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                                            break
                                        else:
                                            collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                                            count = count + 1
                                        
                                        # colission_chain_coordinates[count]
                                for collision_square in collision_chain[::-1]: # loops through list from last to first element
                                    count = len(colission_chain_coordinates) - 1
                                    collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                    collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                    collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                    collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                    #
                                    self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                
                                    if collision_square.previous_direction == None:
                                        collision_square.previous_direction = parent_square.selected_direction                   
                                    # if debugging == True:
                                    #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                                    self.mongo_client.update_parent_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                                    collision_square.body.setOutline(collision_square.outline_color)
                                    count = count - 1
                                    if debugging == True: 
                                        # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{parent_square.selected_direction}]")
                                        pass
                                # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
                                parent_square.body.p1.x = parent_square.body.p1.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p1.y = parent_square.body.p1.y + self.valid_directions[parent_square.selected_direction]['y']
                                parent_square.body.p2.x = parent_square.body.p2.x + self.valid_directions[parent_square.selected_direction]['x']
                                parent_square.body.p2.y = parent_square.body.p2.y + self.valid_directions[parent_square.selected_direction]['y']
                                #
                                self.window.move_by_id(parent_square.tkinter_id, self.valid_directions[parent_square.selected_direction]['x'], self.valid_directions[parent_square.selected_direction]['y'])                    
                                parent_square.previous_direction = parent_square.selected_direction                    
                                self.mongo_client.update_parent_square_coordinates(parent_square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
                                parent_square.body.setOutline(parent_square.outline_color)
                                if debugging == True: 
                                    # print(f"\nDEBUG: Square [{parent_square.square_id}] has moved [{parent_square.selected_direction}]")
                                    pass
                            else:
                                    if debugging == True: 
                                        print(f"\nDEBUG: There are no move valid directions remaining")
                                        print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                                    self.destroySquare(parent_square)
                        elif collision_detected == True and selected_direction_coordinates == None:
                            if debugging == True: 
                                print(f"\nDEBUG: There are no move valid directions remaining")
                                print(f"\n DEBUG: Square {parent_square.square_id} has been crushed")
                            self.destroySquare(parent_square)
        debugging = True
                        
                            
    def moveSquareBody(self, square, selected_direction_coordinates) -> bool:
        """
        Execute movement and update square state.
        Returns:
            bool: True if movement was successful
        """
        if not square.selected_direction or not selected_direction_coordinates:
            return False
            
        debugging = False
        if debugging:
            print(f"\nDEBUG: Moving Square {square.tkinter_id} in direction {square.selected_direction}")
            
        # Get movement deltas
        dx = self.valid_directions[square.selected_direction]['x']
        dy = self.valid_directions[square.selected_direction]['y']
        
        # Update square coordinates
        square.body.p1.x += dx
        square.body.p1.y += dy
        square.body.p2.x += dx
        square.body.p2.y += dy
        
        # Move the square in the window and update its state
        self.window.move_by_id(square.tkinter_id, dx, dy)
        square.previous_direction = square.selected_direction
        
        # Update MongoDB coordinates
        self.mongo_client.update_parent_square_coordinates(square, selected_direction_coordinates)
        
        # Update appearance
        square.body.setOutline(square.outline_color)
        
        # Ensure the window updates
        self.window.update()
        self.window.move_by_id(square.tkinter_id, dx, dy)
        
        # Update movement state and appearance
        square.previous_direction = square.selected_direction
        square.body.setOutline(square.outline_color)
        
        # Update coordinates in database
        self.mongo_client.update_parent_square_coordinates(square, selected_direction_coordinates)
        
        # Ensure we return both updates
        return geometry_updates, selected_direction_coordinates
        
        if debugging:
            print(f"DEBUG: Square [{square.square_id}] moved {square.selected_direction}")
            print(f"DEBUG: New position - P1({square.body.p1.x}, {square.body.p1.y}), P2({square.body.p2.x}, {square.body.p2.y})")

    def moveRandomDirection(self, square):
        """Move square in a random valid direction."""
        debugging = False
        
        # Ensure valid_directions is properly initialized
        if not hasattr(square, 'valid_directions') or not square.valid_directions:
            square.valid_directions = set(self.valid_directions.keys())
            
        # Initialize or reset directions_already_tried
        if not hasattr(square, 'directions_already_tried'):
            square.directions_already_tried = set()
            
        # Try each direction until one works or all have been tried
        while len(square.directions_already_tried) < len(square.valid_directions):
            # Get remaining untried directions
            remaining_directions = square.valid_directions.difference(square.directions_already_tried)
            if not remaining_directions:
                break
                
            # Choose a random direction
            square.selected_direction = choice(list(remaining_directions))
            square.directions_already_tried.add(square.selected_direction)
            
            # Check for collisions
            collision_detected, selected_direction_coordinates = self.mongo_client.collision_check_parent_squareverse(
                square, self, square.selected_direction
            )
            
            if debugging:
                print(f"\nDEBUG: Square [{square.square_id}] trying direction: {square.selected_direction}")
                print(f"DEBUG: Collision detected: {collision_detected}")
                
            if not collision_detected and selected_direction_coordinates:
                # Move the square
                self.moveSquareBody(square, selected_direction_coordinates)
                square.body.setOutline(square.outline_color)
                self.window.update()  # Ensure the movement is displayed
                return True
                
        # If we get here, no valid moves were found
        if debugging:
            print(f"\nDEBUG: No valid moves found for Square [{square.square_id}]")
        square.body.setOutline("Red")  # Visual indicator of stuck square
        self.window.update()
        return False
            # if debugging == True:
            #     print(f"\nDEBUG: There are no more valid directions remaining for Square {square.square_id}")


    def squareChainCollisionCheck(self, square, selected_direction_coordinates):
        debugging = False
        if debugging:
            print(f"\nDEBUG: Checking collision chain for Square [{square.square_id}]")
            
        # Initialize collision tracking
        collision_chain = []
        colission_chain_coordinates = []
        
        # Only process collision if square has greater mass than target
        if square.mass > selected_direction_coordinates['mass']:
            if debugging:
                print(f"DEBUG: Square [{square.square_id}] (mass: {square.mass}) colliding with Square (mass: {selected_direction_coordinates['mass']})")
            collision_chain.append(self.square_objects[selected_direction_coordinates['tkinter_id']])
            count = 0
            while True:
                collision_detected, colission_chain_coordinates_temp = self.mongo_client.collision_check_parent_squareverse(collision_chain[count], self, square.selected_direction) # checks for collision in selected direction
                colission_chain_coordinates.append(colission_chain_coordinates_temp)
                # if debugging == True:
                #     print(f"\nDEBUG: Length of collision chain: {len(collision_chain)}")
                #     print(f"\nDEBUG: Square being checked for collision: {collision_chain[count]}")
                #     print(f"\nDEBUG: Collision chain coordinates temp: {colission_chain_coordinates_temp}")
                #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                
                if collision_detected == False:
                    break
                    
                    # collision_chain[count].body.p1.x = collision_chain[count].body.p1.x + self.valid_directions[square.selected_direction]['x']
                    # collision_chain[count].body.p1.y = collision_chain[count].body.p1.y + self.valid_directions[square.selected_direction]['y']
                    # collision_chain[count].body.p2.x = collision_chain[count].body.p2.x + self.valid_directions[square.selected_direction]['x']
                    # collision_chain[count].body.p2.y = collision_chain[count].body.p2.y + self.valid_directions[square.selected_direction]['y']
                    # #
                    # self.window.move_by_id(smaller_square_object.tkinter_id, self.valid_directions[square.selected_direction]['x'], self.valid_directions[square.selected_direction]['y'])                
                    # if smaller_square_object.previous_direction == None:
                    #     smaller_square_object.previous_direction = square.selected_direction                   
                    # self.mongo_client.update_square_coordinates(smaller_square_object, selected_direction_coordinates_additional) # updates global coordinates for Square in MongoDB
                    # smaller_square_object.body.setOutline(smaller_square_object.outline_color)
                    # if debugging == True: 
                    #     # print(f"\nDEBUG: Square [{square.square_id}] has moved [{square.selected_direction}]")
                    #     pass
                elif collision_detected == True and colission_chain_coordinates[count] == None:
                    #work in progress
                    # added logic to delete square as a temporary fix until logic is completed
                    if debugging == True:
                        print(f"\n DEBUG: Chain collision Square has hit Squareverse border\n")
                    self.destroySquare(collision_chain[count])
                    del collision_chain[-1]
                    del colission_chain_coordinates[-1]
                    if debugging == True:
                        print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                        print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                    
                    break
                    # pass
                else:
                    # Need to add logic for comparing mass of Square being checked with Square colliding with
                    if collision_chain[count].mass <= colission_chain_coordinates[count]['mass']:
                        if debugging == True:
                            print(f"\n DEBUG: Chain collision Square has been crushed")
                        self.destroySquare(collision_chain[count])
                        del collision_chain[-1]
                        del colission_chain_coordinates[-1]
                        # if debugging == True:
                            # print(f"\n DEBUG: Chain collisions after deleting: {collision_chain}\n")
                            # print(f"\n DEBUG: Chain collision coordinates after deleting: {colission_chain_coordinates}\n")
                        break
                    else:
                        collision_chain.append(self.square_objects[colission_chain_coordinates[count]['tkinter_id']])
                        count = count + 1
                    
                    # colission_chain_coordinates[count]
            for collision_square in collision_chain[::-1]: # loops through list from last to first element
                count = len(colission_chain_coordinates) - 1
                collision_square.body.p1.x = collision_square.body.p1.x + self.valid_directions[square.selected_direction]['x']
                collision_square.body.p1.y = collision_square.body.p1.y + self.valid_directions[square.selected_direction]['y']
                collision_square.body.p2.x = collision_square.body.p2.x + self.valid_directions[square.selected_direction]['x']
                collision_square.body.p2.y = collision_square.body.p2.y + self.valid_directions[square.selected_direction]['y']
                #
                self.window.move_by_id(collision_square.tkinter_id, self.valid_directions[square.selected_direction]['x'], self.valid_directions[square.selected_direction]['y'])                
                if collision_square.previous_direction == None:
                    collision_square.previous_direction = square.selected_direction                   
                # if debugging == True:
                #     print(f"\nDEBUG: Collision chain coordinates: {colission_chain_coordinates}\n")
                self.mongo_client.update_square_coordinates(collision_square, colission_chain_coordinates[count]) # updates global coordinates for Square in MongoDB
                collision_square.body.setOutline(collision_square.outline_color)
                count = count - 1
                if debugging == True: 
                    # print(f"\nDEBUG: Square [collision_square.square_id}] has moved [{square.selected_direction}]")
                    pass
            # updates Point 1 and Point 2 coordinates for parent Square (used for drawing parent Square to window)
            square.body.p1.x = square.body.p1.x + self.valid_directions[square.selected_direction]['x']
            square.body.p1.y = square.body.p1.y + self.valid_directions[square.selected_direction]['y']
            square.body.p2.x = square.body.p2.x + self.valid_directions[square.selected_direction]['x']
            square.body.p2.y = square.body.p2.y + self.valid_directions[square.selected_direction]['y']
            #
            self.window.move_by_id(square.tkinter_id, self.valid_directions[square.selected_direction]['x'], self.valid_directions[square.selected_direction]['y'])                    
            square.previous_direction = square.selected_direction                    
            self.mongo_client.update_parent_square_coordinates(square, selected_direction_coordinates) # updates global coordinates for Square in MongoDB
            square.body.setOutline(square.outline_color)
            if debugging == True: 
                # print(f"\nDEBUG: Square [{square.square_id}] has moved [{square.selected_direction}]")
                pass
            



    # def moveChildSquares(self, number_of_cycles, square_p):

    #     for _ in range(number_of_cycles):
    #         print(f"Moving all children for Square [{square_p.square_id}]") #debug
    #         for square in self.created_squares:

    #             square.moveSquareChild(self, square_p)

    #     self.checkSquarePositions()
        
    #     self.direction_with_the_most_squares = max(i for i in self.square_locations.values())

    #     # print(f"\n\nMax Squares in a direction: {self.direction_with_the_most_squares}") #debug

    #     tie_breaker = choice([i for i in self.square_locations.keys() if self.square_locations.get(i) == self.direction_with_the_most_squares])

    #     # print(f"\n\nDirection with the most Squares after tie-breaker: {tie_breaker}") #debug

    #     # return(max(self.square_locations, key=lambda key: self.square_locations[key]))

    #     return tie_breaker
    
    
    
    # def checkSquarePositions(self):

    #     # self.squares_left = 0
    #     # self.squares_right = 0
    #     # self.squares_up = 0
    #     # self.squares_down = 0

    #     self.square_locations = {"left": 0, "right": 0, "up": 0, "down": 0}
        
    #     for square in self.created_squares:

    #         square_center = square.body.getCecanvas = self.square_locations["left"] + 1
    #         else:
    #             self.square_locations["right"] = self.square_locations["right"] + 1

    #         if int(square_center_coordinates[1]) < self.center_point_coordinate:
    #             self.square_locations["up"] = self.square_locations["up"] + 1
    #         else:
    #             self.square_locations["down"] = self.square_locations["down"] + 1

    #     # print(f"\n\nSquares left: {self.square_locations['left']}\n\nSquares right: {self.square_locations['right']}\n\nSquares up: {self.square_locations['up']}\n\nSquares down: {self.square_locations['down']}") #debug
    #     # print(max(self.square_locations, key=lambda key: self.square_locations[key]))

    def _process_move_batch(self):
        """Process a batch of queued square movements."""
        if not self._move_batch:
            return
            
        # Execute all visual movements
        for move in self._move_batch:
            square = move['square']
            dx, dy = move['dx'], move['dy']
            
            # Update visual position
            square.body.p1.x += dx
            square.body.p1.y += dy
            square.body.p2.x += dx
            square.body.p2.y += dy
            self.window.move_by_id(square.tkinter_id, dx, dy)
            
            # Update square state
            square.previous_direction = square.selected_direction
            square.body.setOutline(square.outline_color)
            
        # Bulk update MongoDB coordinates
        self.mongo_client.bulk_update_coordinates(self._move_batch)
        
        # Clear the batch
        self._move_batch = []

    def destroySquare(self, square):
        '''
        Logic for deleting Square:
        - Undraw object from pygame window
        - Delete Square info from MongoDB
        - Delete Square object in Squareverse square_objects
        - Clean up object references
        '''
        debugging = True
        
        square_id = square.tkinter_id
        
        # Update MongoDB
        mongo_query = { "tkinter_id": square.tkinter_id }
        mongo_updated_value = { "$set": { "tkinter_id": None, "previous_direction": None, "mass": None }}
        self.mongo_client.update_mongodb(mongo_query, mongo_updated_value)
        
        # Remove from window tracking
        if square.tkinter_id in self.window.shapes:
            self.window.delItem(square)
            
        # Clean up object references
        if square.tkinter_id in self.square_objects:
            del self.square_objects[square.tkinter_id]
            
        # Force window update
        self.window.update()
        
        del square
        
        # if debugging == True:
        #     print(f"\nDEBUG: Square {square_id} has been destroyed!\n")


    # completely and utterly destroys the parent Squareverse and all of its child Squareverses
    def destroySquareverse(self):
        
        print(f"\nDEBUG: Destroying Squareverse #{self.squareverse_id} T__T\n") # DEBUG
        
        # deletes all shape objects
        print(f"-> 1/3 Destroying Squares...\n") # DEBUG
        del self.window.items
        del self.window.squares
        
        
        # deletes all data from Squareverse MongoDB
        print(f"-> 2/3 Destroying data in MongoDB...\n") # DEBUG
        self.mongo_client.delete_squareverse_db()
        

        # gc.disable() # TESTING
        # self.window.autoflush = True # TESTING

        # gc.enable() # TESTING
        # self.window.flush() # TESTING
        # gc.collect(generation=2) # TESTING
        print(f"-> 3/3 Destroying Squareverse...\n")
        self.window.close()

        print(f"\nSquareverse destroyed!!!\n") # DEBUG
        
        

        
        
        




class ChildSquareverse(Squareverse):


    def __init__(self, parent_square_tkinter_id, child_squareverse_name):

        super().__init__(parent_square_tkinter_id, child_squareverse_name)
        self.child_square_ids = []
        

    def createSquareverseWindow(self, squareverse_size, squareverse_grid_spacing, parent_square, parent_squareverse):

        self.window_background_color = parent_square.body_color
        self.grid_color = color_rgb(255, 255, 255)

        self.squareverse_size = squareverse_size # TESTING
        self.squareverse_grid_spacing = squareverse_grid_spacing # TESTING
        self.max_number_of_squares = int(round((self.squareverse_size / self.squareverse_grid_spacing)) ** 2)
        self.total_grid_lines = int(round((self.squareverse_size // self.squareverse_grid_spacing), 0) + 1) # TESTING
        
        self.top_border = self.squareverse_grid_spacing
        self.bottom_border = self.squareverse_size + self.squareverse_grid_spacing
        self.left_border = self.squareverse_grid_spacing
        self.right_border = self.squareverse_size + self.squareverse_grid_spacing
        self.center_point_coordinate = ((self.squareverse_size + self.squareverse_grid_spacing) + self.squareverse_grid_spacing) // 2
        
        self.valid_directions = {
        "up": {
            "x": 0, 
            "y": (self.squareverse_grid_spacing * - 1), 
            "i": "down"
            }, 
        "down": {
            "x": 0, 
            "y": self.squareverse_grid_spacing, 
            "i": "up"
            }, 
        "left": {
            "x": (self.squareverse_grid_spacing * - 1), 
            "y": 0,
            "i": "right"
            },
        "right": {
            "x": self.squareverse_grid_spacing, 
            "y": 0,
            "i": "left"}}


        # everything after this can be commented out if window isn't required for child Squareverse
        # self.squareverse_window_size = self.squareverse_size + (self.squareverse_grid_spacing * 2)

        # self.window = GraphWin(title = self.squareverse_name, width = self.squareverse_window_size, height = self.squareverse_window_size)
        
        # self.window.setBackground(self.window_background_color)

        # self.center_point = Point(self.center_point_coordinate, self.center_point_coordinate) #testing
        # self.center_point.setFill("Orange") #testing


        # self.createSquareverseGrid()

        # create Squareverse child coordinates in Mongo
        parent_squareverse.mongo_client.create_child_squareverse_coordinates(self.squareverse_grid_spacing, self.total_grid_lines, self.child_square_ids, parent_square.tkinter_id)



    def createSquares(self, number_of_squares):

        # sets limits for where Squares can spawn in the Squareverse
        self.squareverse_max_xy = self.squareverse_size + self.squareverse_grid_spacing

        for _ in range(number_of_squares):
                       
            square_id = len(self.created_squares)

            square = SquareChild(square_id, self)
            
            self.number_of_empty_grids = self.max_number_of_squares - len(self.created_squares)
            
            self.duplicate_square_check = True
            
            if self.number_of_empty_grids == 0:
                 
                # print(f"\n\nThere are [{self.number_of_empty_grids}] empty grids remaining (no more grid space)") #debug

                break
                
            else:
            
                while self.duplicate_square_check == True:
                    
                    top_left_corner_x = randrange(self.squareverse_grid_spacing, self.squareverse_max_xy, self.squareverse_grid_spacing)
                        
                    top_left_corner_y = randrange(self.squareverse_grid_spacing, self.squareverse_max_xy, self.squareverse_grid_spacing)

                    bottom_right_corner_x = top_left_corner_x + self.squareverse_grid_spacing
                    
                    bottom_right_corner_y = top_left_corner_y + self.squareverse_grid_spacing

                    # checks for duplicate Squares
                    self.duplicate_square_check = self.duplicateSquareCheck(square, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y)

            # adds coordinates to Square positions set for tracking
            self.square_positions.add(square.current_coordinates)

            # adds Square to created Squares array
            # self.created_squares.append(square) # commented out for testing

            square.drawSquareBody(self, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y)


    # **may not be needed as squares are identified when creating coordinates - WORK IN PROGRESS
    def createChildSquares(self, number_of_squares, parent_square_tkinter_id, parent_squareverse):
            
        # fetches random list of unoccupied coordinates from MongoDB
        available_coordinates = parent_squareverse.mongo_client.get_available_child_squareverse_coordinates(number_of_squares, parent_square_tkinter_id)
    
        for coordinate in available_coordinates:

            self.child_square_ids.append(coordinate["_id"])
            # square_id = coordinate["_id"]
            # # square = Square(square_id, self)

            top_left_corner_x = coordinate["top_left_corner_x"]
            # top_left_corner_y = coordinate["top_left_corner_y"]
            # bottom_right_corner_x = coordinate["bottom_right_corner_x"]
            # bottom_right_corner_y = coordinate["bottom_right_corner_y"]

            mongo_query = { "_id": coordinate["_id"] }
            mongo_updated_value = { "$set": { "child_square_id": True }}

            parent_squareverse.mongo_client.update_mongodb_child_squareverse(mongo_query, mongo_updated_value, parent_square_tkinter_id)


    def moveChildSquares(self, parent_squareverse, parent_square, number_of_cycles):

        child_square_coordinates = parent_squareverse.mongo_client.get_child_square_coordinates(self.child_square_ids, parent_square.tkinter_id)
        
        for i in range(number_of_cycles):
            
            # print(f"\n\nDEBUG: Moved all children for Square #{parent_square.tkinter_id} {i+1} times") # DEBUG
            
            for child_square_coordinate in child_square_coordinates:

                # previous_direction = child_square_coordinate["previous_direction"]
                self.moveChildSquare(parent_squareverse, parent_square, child_square_coordinate)

        # self.checkSquarePositions()
        single_direction, child_square_coordinates_count = self.checkChildSquarePositions(parent_squareverse, parent_square)

        if single_direction != None:

            print(f"\n\nDEBUG: All child Squares are in a single direction: {single_direction}") # DEBUG
            
            selected_direction = single_direction
            single_direction = True
            
            return single_direction, selected_direction

        else:
        
            single_direction = False          
            # print(f"DEBUG: Child Squares coordinate count: {child_square_coordinates_count}") # DEBUG
            
            selected_direction = choice([k for k in child_square_coordinates_count.keys() if child_square_coordinates_count.get(k) == max(v for v in child_square_coordinates_count.values())])
            # print(f"DEBUG: Max Squares in a direction: {max(v for v in child_square_coordinates_count.values())}") # DEBUG
            
            # print(f"DEBUG: Direction selected by child Squares: {selected_direction}\n\n") # DEBUG
            
            return single_direction, selected_direction

    
    
    
    def moveSquareChildren(self, number_of_cycles, parent_squareverse):

        for i in range(number_of_cycles):
            
            # print(f"\n\nMoved all children for Square [{square_p.square_id}] {i} times") #debug
            for square in self.created_squares:

                square.moveSquareChild(self, parent_squareverse)

        self.checkSquarePositions()
        # self.checkChildSquarePositions(parent_squareverse, )

        if self.single_location != None:

            return self.single_location

        else:
        
            self.direction_with_the_most_squares = max(i for i in self.square_locations.values())

            # print(f"\n\nMax Squares in a direction: {self.direction_with_the_most_squares}") #debug

            tie_breaker = choice([i for i in self.square_locations.keys() if self.square_locations.get(i) == self.direction_with_the_most_squares])

            # print(f"\n\nDirection with the most Squares after tie-breaker: {tie_breaker}") #debug

            # return(max(self.square_locations, key=lambda key: self.square_locations[key]))

            return tie_breaker
    
    
    
    def checkSquarePositions(self):

        # self.squares_left = 0
        # self.squares_right = 0
        # self.squares_up = 0
        # self.squares_down = 0

        self.square_locations = {"left": 0, "right": 0, "up": 0, "down": 0}
        self.single_location = None
        
        for square in self.created_squares:

            square_center = square.body.getCenterCoordinates()
            square_center_coordinates = square_center.split(':')

            if int(square_center_coordinates[0]) < self.center_point_coordinate:
                
                self.square_locations["left"] = self.square_locations["left"] + 1
            
            else:
                
                self.square_locations["right"] = self.square_locations["right"] + 1

            if int(square_center_coordinates[1]) < self.center_point_coordinate:
                
                self.square_locations["up"] = self.square_locations["up"] + 1
            
            else:
                
                self.square_locations["down"] = self.square_locations["down"] + 1

        if int(self.square_locations["left"]) == len(self.created_squares):

            self.single_location = "left"

        elif int(self.square_locations["right"]) == len(self.created_squares):

            self.single_location = "right"

        elif int(self.square_locations["down"]) == len(self.created_squares):

            self.single_location = "down"

        elif int(self.square_locations["up"]) == len(self.created_squares):

            self.single_location = "up"

        # print(f"\n\nSquares left: {self.square_locations['left']}\n\nSquares right: {self.square_locations['right']}\n\nSquares up: {self.square_locations['up']}\n\nSquares down: {self.square_locations['down']}") #debug
        # print(max(self.square_locations, key=lambda key: self.square_locations[key]))

    def checkChildSquarePositions(self, parent_squareverse, parent_square):

        single_location = None
        child_square_coordinates_count = parent_squareverse.mongo_client.count_child_square_coordinates(self.center_point_coordinate, parent_square.tkinter_id)

        if "up" in child_square_coordinates_count:
            
            if child_square_coordinates_count["up"] == len(self.child_square_ids):

                single_location = "up"

        elif "down" in child_square_coordinates_count:
        
            if child_square_coordinates_count["down"] == len(self.child_square_ids):

                single_location = "down"

        elif "left" in child_square_coordinates_count:
        
            if child_square_coordinates_count["left"] == len(self.child_square_ids):

                single_location = "left"

        elif "right" in child_square_coordinates_count:
            
            if child_square_coordinates_count["right"] == len(self.child_square_ids):

                single_location = "right"

        return single_location, child_square_coordinates_count

    
    # WORK IN PROGRESS #
    def moveChildSquare(self, parent_squareverse, parent_square, child_square_coordinate):
        
        valid_directions = set(self.valid_directions.keys())
        directions_already_tried = parent_square.directions_already_tried.copy() #inherits directions tried from parent Square
        # print(f"\n\nDirections already tried by Square parent are [{self.directions_already_tried}]") #debug
        remaining_directions = set()
        selected_direction = None
        previous_direction = child_square_coordinate["previous_direction"] #testing
        
        # self.number_of_collisions = copy(square_p.number_of_collisions) #inherits number of collisions from parent Square
        collision_detected = True

        # resets color and outline for Square
        # self.body.setFill(self.body_color) #not required for child Square
        # self.body.setOutline(self.outline_color) #not required for child Square


        if previous_direction == None or previous_direction in directions_already_tried: # prevents Child Square from trying a direction already tried by Parent Square

            # self.child_squareversehild.checkSquarePositions() #testing
            
            while len(directions_already_tried) != len(valid_directions):

                remaining_directions = valid_directions.difference(directions_already_tried)
                # print(f"\n\nRemaining directions for child Square {child_square_coordinate["_id"]} are {remaining_directions}") # DEBUG
                selected_direction = choice(list(remaining_directions))
                directions_already_tried.add(selected_direction)
                
                # checks for collision in selected direction
                collision_detected, selected_direction_coordinates = parent_squareverse.mongo_client.collision_check_child_squareverse(self, parent_square, child_square_coordinate, selected_direction)

                if collision_detected == False:

                    
                    parent_squareverse.mongo_client.update_child_square_coordinates(parent_square, child_square_coordinate, selected_direction, selected_direction_coordinates)
                    
                    
                    # # sets occupied to False after moving if "empty" coordinate found
                    # mongo_query = {"$and":[ {"occupied": {"$exists": False }}, {"top_left_corner_x": child_square_coordinate["top_left_corner_x"], "top_left_corner_y": child_square_coordinate["top_left_corner_y"] }]}
                    # mongo_updated_value = { "$set": { "occupied": False }}
                    
                    # parent_squareverse.mongo_client.update_mongodb(mongo_query, mongo_updated_value)

                    
                    # # updates coordinates for child Square in MongoDB
                    # mongo_query = { "_id": child_square_coordinate["_id"] }                    
                    # mongo_updated_value = { "$set": { "top_left_corner_x": child_square_coordinate["top_left_corner_x"] + self.valid_directions[selected_direction]['x'],  "top_left_corner_y": child_square_coordinate["top_left_corner_y"] + self.valid_directions[selected_direction]['y'], "bottom_right_corner_x": child_square_coordinate["bottom_right_corner_x"] + self.valid_directions[selected_direction]['x'], "bottom_right_corner_y": child_square_coordinate["bottom_right_corner_y"]  + self.valid_directions[selected_direction]['y'], "previous_direction": selected_direction }}

                    # parent_squareverse.mongo_client.update_mongodb(mongo_query, mongo_updated_value)

                    # # **need to add logic for updating empty Square occupied to False (see line 523)
                    # mongo_query = {"$and":[ {"occupied": {"$exists": True }}, {"top_left_corner_x": square.body.p1.x, "top_left_corner_y": square.body.p1.y }]}
                    
                    # child_square_coordinate["top_left_corner_x"] = child_square_coordinate["top_left_corner_x"] + self.valid_directions[selected_direction]['x']
                    # child_square_coordinate["top_left_corner_y"] = child_square_coordinate["top_left_corner_y"] + self.valid_directions[selected_direction]['y']
                    # child_square_coordinate["bottom_right_corner_x"] = child_square_coordinate["bottom_right_corner_x"] + self.valid_directions[selected_direction]['x']
                    # child_square_coordinate["bottom_right_corner_y"] = child_square_coordinate["bottom_right_corner_y"]  + self.valid_directions[selected_direction]['y']
                    
                    
                    
                    # self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                    # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")
                    
                    # self.previous_direction = self.selected_direction

                    

                    # updates global coordinates for Square
                    # print(f"\n\n{self.current_coordinates}")
                    # squareverse.square_positions.remove(self.current_coordinates)
                    # self.current_coordinates = self.body.getCoordinates()
                    # squareverse.square_positions.add(self.current_coordinates)

                    break
                    
                elif collision_detected == True:

                    pass
                    # directions_already_tried.add(selected_direction)
                    # print(f"Directions already tried are [{directions_already_tried}]") #D

                    # remaining_directions = valid_directions.difference(directions_already_tried)
                    # print(f"\n\nRemaining directions are [{remaining_directions}]")

            else:

                pass
                # print("There are no move valid directions remaining")
                # self.body.setFill("Red")


        elif previous_direction != None and directions_already_tried != None:

            selected_direction = previous_direction

            directions_already_tried.add(selected_direction)

            # self.collision_detected = self.collisionCheck(self, self.selected_direction)
            collision_detected, selected_direction_coordinates = parent_squareverse.mongo_client.collision_check_child_squareverse(self, parent_square, child_square_coordinate, selected_direction)

            if collision_detected == False:

                parent_squareverse.mongo_client.update_child_square_coordinates(parent_square, child_square_coordinate, selected_direction, selected_direction_coordinates)
                
                # self.body.move(self.valid_directions[self.selected_direction]['x'], self.valid_directions[self.selected_direction]['y'])
            
                # # updates global coordinates for Square
                # self.square_positions.remove(self.current_coordinates)
                # self.current_coordinates = self.body.getCoordinates() 
                # self.square_positions.add(self.current_coordinates)
        
            elif collision_detected == True:

                # checks if the inverse direction has already been tried
                if self.valid_directions[selected_direction]['i'] not in directions_already_tried:

                    selected_direction = self.valid_directions[selected_direction]['i']

                    directions_already_tried.add(selected_direction)

                    collision_detected, selected_direction_coordinates = parent_squareverse.mongo_client.collision_check_child_squareverse(self, parent_square, child_square_coordinate, selected_direction)
                    # collision_detected = self.collisionCheck(self, self.selected_direction)

                    if collision_detected == False:

                        parent_squareverse.mongo_client.update_child_square_coordinates(parent_square, child_square_coordinate, selected_direction, selected_direction_coordinates)
                        
                        # self.body.move(self.valid_directions[self.selected_direction]['x'], self.valid_directions[self.selected_direction]['y'])
                        # # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

                        # self.previous_direction = self.selected_direction
                        
                        # # updates global coordinates for Square
                        # self.square_positions.remove(self.current_coordinates)
                        # self.current_coordinates = self.body.getCoordinates()
                        # self.square_positions.add(self.current_coordinates)

                    elif collision_detected == True:

                        while len(directions_already_tried) != len(valid_directions):

                            remaining_directions = valid_directions.difference(directions_already_tried)
                            # print(f"\n\nRemaining directions for Square [{self.square_id}] are {remaining_directions}")

                            selected_direction = choice(list(remaining_directions))

                            directions_already_tried.add(selected_direction)

                            # checks for collision in selected direction
                            collision_detected, selected_direction_coordinates = parent_squareverse.mongo_client.collision_check_child_squareverse(self, parent_square, child_square_coordinate, selected_direction)
                            # self.collision_detected = self.collisionCheck(self, self.selected_direction)

                            if collision_detected == False:

                                parent_squareverse.mongo_client.update_child_square_coordinates(parent_square, child_square_coordinate, selected_direction, selected_direction_coordinates)
                                
                                # self.body.move(self.valid_directions[self.selected_direction]['x'], self.valid_directions[self.selected_direction]['y'])
                                # # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")
                                
                                # self.previous_direction = self.selected_direction

                                # # updates global coordinates for Square
                                # self.square_positions.remove(self.current_coordinates)
                                # self.current_coordinates = self.body.getCoordinates()
                                # self.square_positions.add(self.current_coordinates)

                                break
                                
                            elif collision_detected == True:

                                pass

                else:

                    while len(directions_already_tried) != len(valid_directions):

                        remaining_directions = valid_directions.difference(directions_already_tried)
                        # print(f"\n\nRemaining directions for Square [{self.square_id}] are {remaining_directions}")

                        selected_direction = choice(list(remaining_directions))

                        directions_already_tried.add(selected_direction)

                        collision_detected, selected_direction_coordinates = parent_squareverse.mongo_client.collision_check_child_squareverse(self, parent_square, child_square_coordinate, selected_direction)

                        if collision_detected == False:

                            parent_squareverse.mongo_client.update_child_square_coordinates(parent_square, child_square_coordinate, selected_direction, selected_direction_coordinates)
                            
                            
                            # self.body.move(self.valid_directions[self.selected_direction]['x'], self.valid_directions[self.selected_direction]['y'])
                            # # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")
                            
                            # self.previous_direction = self.selected_direction

                            # # updates global coordinates for Square
                            # self.square_positions.remove(self.current_coordinates)
                            # self.current_coordinates = self.body.getCoordinates()
                            # self.square_positions.add(self.current_coordinates)

                            break
                            
                        elif collision_detected == True:

                            pass

        # checks if child Square has a previous direction and parent Square has not tried any directions
        elif previous_direction != None and directions_already_tried == None:

            selected_direction = previous_direction

            directions_already_tried.add(selected_direction)

            # checks for collision in selected direction
            collision_detected, selected_direction_coordinates = parent_squareverse.mongo_client.collision_check_child_squareverse(self, parent_square, child_square_coordinate, selected_direction)
            # self.collision_detected = self.collisionCheck(self, self.selected_direction)

            if collision_detected == False:

                parent_squareverse.mongo_client.update_child_square_coordinates(parent_square, child_square_coordinate, selected_direction, selected_direction_coordinates)
                
                # self.body.move(self.valid_directions[self.selected_direction]['x'], self.valid_directions[self.selected_direction]['y'])
            
                # # updates global coordinates for Square
                # self.square_positions.remove(self.current_coordinates)
                # self.current_coordinates = self.body.getCoordinates() 
                # self.square_positions.add(self.current_coordinates)
        
            elif collision_detected == True:

            # self.directions_already_tried.add(selected_direction)
            # print(f"Directions already tried are [{directions_already_tried}]") #D

            # self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
            # print(f"\n\nRemaining directions are [{remaining_directions}]")
            
                selected_direction = self.valid_directions[selected_direction]['i']

                directions_already_tried.add(selected_direction)

                # checks for collision in selected direction
                collision_detected, selected_direction_coordinates = parent_squareverse.mongo_client.collision_check_child_squareverse(self, parent_square, child_square_coordinate, selected_direction)
                # self.collision_detected = self.collisionCheck(self, self.selected_direction)

                if collision_detected == False:

                    parent_squareverse.mongo_client.update_child_square_coordinates(parent_square, child_square_coordinate, selected_direction, selected_direction_coordinates)
                    
                    # self.body.move(self.valid_directions[self.selected_direction]['x'], self.valid_directions[self.selected_direction]['y'])
                    # # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

                    # self.previous_direction = self.selected_direction
                    
                    # # updates global coordinates for Square
                    # self.square_positions.remove(self.current_coordinates)
                    # self.current_coordinates = self.body.getCoordinates()
                    # self.square_positions.add(self.current_coordinates)

                # attempts to randomly move in any remaining direction
                elif collision_detected == True:

                    while len(directions_already_tried) != len(valid_directions):

                        remaining_directions = valid_directions.difference(directions_already_tried)
                        # print(f"\n\nRemaining directions for Square [{self.square_id}] are {remaining_directions}")

                        selected_direction = choice(list(remaining_directions))

                        directions_already_tried.add(selected_direction)

                        # checks for collision in selected direction
                        collision_detected, selected_direction_coordinates = parent_squareverse.mongo_client.collision_check_child_squareverse(self, parent_square, child_square_coordinate, selected_direction)
                        # self.collision_detected = self.collisionCheck(self, self.selected_direction)

                        if collision_detected == False:

                            parent_squareverse.mongo_client.update_child_square_coordinates(parent_square, child_square_coordinate, selected_direction, selected_direction_coordinates)

                            # self.body.move(self.valid_directions[self.selected_direction]['x'], self.valid_directions[self.selected_direction]['y'])
                            # # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")
                            
                            # self.previous_direction = self.selected_direction

                            # # updates global coordinates for Square
                            # self.square_positions.remove(self.current_coordinates)
                            # self.current_coordinates = self.body.getCoordinates()
                            # self.square_positions.add(self.current_coordinates)

                            break
                            
                        elif collision_detected == True:

                            selected_direction = self.valid_directions[selected_direction]['i']

                            directions_already_tried.add(selected_direction)

                            # checks for collision in selected direction
                            collision_detected, selected_direction_coordinates = parent_squareverse.mongo_client.collision_check_child_squareverse(self, parent_square, child_square_coordinate, selected_direction)
                            # self.collision_detected = self.collisionCheck(self, self.selected_direction)

                            if collision_detected == False:

                                parent_squareverse.mongo_client.update_child_square_coordinates(parent_square, child_square_coordinate, selected_direction, selected_direction_coordinates)
                                
                                # self.body.move(self.valid_directions[self.selected_direction]['x'], self.valid_directions[self.selected_direction]['y'])
                                # # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")
                            
                                # self.previous_direction = self.selected_direction

                                # # updates global coordinates for Square
                                # self.square_positions.remove(self.current_coordinates)
                                # self.current_coordinates = self.body.getCoordinates()
                                # self.square_positions.add(self.current_coordinates)

                                break
                            
                            elif collision_detected == True:

                                pass
    





# ---CLASSLESS FUNCTIONS--- 



# def createSquareverseSimulation():


#     squareverse_id = randint(0, 100)
#     squareverse_name = f"Squareverse {squareverse_id}"
#     squareverse_default_size = 5
#     invalid_squareverse_size = True


#     while invalid_squareverse_size == True:

#         squareverse_size = input("\n\nSelect size for Squareverse (1 - 10): ") #info
        
#         if len(squareverse_size) == 0:

#             squareverse_size = squareverse_default_size
#             invalid_squareverse_size = False

#         elif float(squareverse_size) % 1 != 0:

#             print("\n\nPlease choose a whole number for Squareverse size") #info

#         elif int(squareverse_size) <= 10 and int(squareverse_size) >= 1:
        
#             invalid_squareverse_size = False

#         else:

#             print("\n\nPlease choose a valid size for Squareverse") #info

#     squareverse_size = (int(squareverse_size) * 100) #calculates Squareverse window size in px
#     valid_grid_sizes = [i for i in range(10, ((squareverse_size // 10) + 1)) if squareverse_size % i == 0 and (squareverse_size / i) % 2 == 0]
#     # print(f"\n\nList of valid grid sizes are [{valid_grid_sizes}]") #debug
#     squareverse_grid_spacing = choice(valid_grid_sizes)
#     # print(f"\n\nSelected grid spacing is [{squareverse_grid_spacing}]") #debug
#     squareverse = Squareverse(squareverse_id, squareverse_name)
#     squareverse.createSquareverseWindow(squareverse_size, squareverse_grid_spacing)
    
#     print(f"\n\n{squareverse.squareverse_name} has been successfully created") #debug


#     return squareverse



# def showSquareverseMenu(squareverse):

#     # valid_options = ["s", "d", "a", "m", "e"]

#     while True:
       
#         user_selection = input("\n\nPlease select what you want to do:\nSpawn a Square (s)\nDelete a Square (d)\nDelete all Squares (a)\nMove Squares (m)\nEnd the Squareverse simulation (e)\n\nOption: ")
#         # assert user_selection in valid_options, "E: that was not a valid option!"

#         if user_selection == "s":
            
#             # draw_squares = True
#             number_of_squares = input("\n\nEnter the number of Squares to spawn (m = max allowed, h = half max, q = quarter max): ")

#             if number_of_squares == "m":
                
#                 number_of_squares = (squareverse.max_number_of_squares - len(squareverse.created_squares))
            
#             elif number_of_squares == "h":
                
#                 number_of_squares = squareverse.max_number_of_squares // 2
            
#             elif number_of_squares == "q":
                
#                 number_of_squares = squareverse.max_number_of_squares // 4
            
#             else:
                
#                 pass

#             squareverse.createSquares(int(number_of_squares))

#         elif user_selection == "d":
            
#             pass
        
#         elif user_selection == "a":
            
#             pass
       
#         elif user_selection == "m":
            
#             squareverse.moveAllSquares()

#         else:
            
#             mongo.delete_valid_directions()
#             squareverse.destroySquareverse()
            
#             break








class ParentSquare():

    
    def __init__(self, parent_squareverse, square_id):
        
        # def needed
        self.previous_direction = None

        # not sure if still needed
        self.square_id = square_id
        self.valid_directions = set(parent_squareverse.valid_directions.keys())
        # self.current_coordinates = None
        # self.valid_directions = None
        # self.number_of_collisions = 0

        self.top_left_corner_x = 0
        self.top_left_corner_y = 0
        self.bottom_right_corner_x = 0
        self.bottom_right_corner_y = 0  
        
   

        # create_window = False
        # draw_squares = False
        # self.child_squareversehild.createSquareverseWindow(squareverse_parent.squareverse_size, squareverse_parent.squareverse_grid_spacing, create_window)
        # self.child_squareversehild.createSquares((self.child_squareversehild.max_number_of_squares // 2), draw_squares)



    # **look into moving this function into the parent Squareverse class
    def drawSquareBody(self, parent_squareverse, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):
        self.mass = randrange(0, 255)  # add mass to Square (0-255 for valid RGB)
        # sets color schemes allowed for parent Square
        self.body_color = color_rgb(
            max(0, min(255, 255 - self.mass)),
            max(0, min(255, 255 - self.mass)),
            max(0, min(255, 255 - self.mass))
        )
        self.outline_color = color_rgb(
            max(0, min(255, randrange(0, 255))),
            max(0, min(255, randrange(0, 255))),
            max(0, min(255, randrange(0, 255)))
        )
        # self.outline_width = 4
        # self.outline_width = (parent_squareverse.squareverse_grid_spacing / 10)
        self.outline_width = 1
        # print(f"\nOutline size (px): {self.outline_width}\n")
        
        # self.body = Rectangle(Point((top_left_corner_x + (self.outline_width / 2)), (top_left_corner_y + (self.outline_width / 2))), Point((bottom_right_corner_x - (self.outline_width / 2)), (bottom_right_corner_y - (self.outline_width / 2))))
        # self.body = Rectangle(Point((top_left_corner_x + (self.outline_width / 2)), (top_left_corner_y + (self.outline_width / 2))), Point((bottom_right_corner_x - (self.outline_width / 2)), (bottom_right_corner_y - (self.outline_width / 2))))
        # Create pygame-compatible Rectangle
        self.body = Rectangle(Point(top_left_corner_x, top_left_corner_y), Point(bottom_right_corner_x, bottom_right_corner_y))
        
        # Set appearance properties
        self.body.setFill(self.body_color)
        self.body.setOutline(self.outline_color)
        self.body.setWidth(self.outline_width)
        
        # Draw and get ID, then update display
        self.tkinter_id = self.body.draw_square(parent_squareverse.window, self)
        parent_squareverse.window.update()
        

        # self.child_squareverse = ChildSquareverse(self.tkinter_id, f"{parent_squareverse.squareverse_name} CHILD [{self.tkinter_id}]")
        # self.child_squareverse.createSquareverseWindow(squareverse_p.squareverse_size, squareverse_p.squareverse_grid_spacing, self.body_color)
        # self.child_squareverse.createSquareverseWindow(300, 25, self, parent_squareverse)# testing hard-coded child Squareverse size


        # self.child_squareverse.createSquares((self.child_squareverse.max_number_of_squares // 6)) # controls how many child Squares are created
        # self.child_squareverse.createChildSquares((self.child_squareverse.max_number_of_squares // 6), self.tkinter_id, parent_squareverse) # controls how many child Squares are created / commented out as squares are identified when creating coordinates

        # self.child_squareverse.createSquares(10)

        # self.child_squareversehild.createSquares(10, draw_squares) #testing

        # print(len(self.child_squareversehild.square_positions)) #debug
        # print(self.child_squareversehild.square_positions) #debug


        # print(f"\n\nTk ID for Square is [{tk_id}]") #D
        # print(f"Square body has been successfully drawn") #D



    # def createSquareChild(self, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):

    #     self.body = Rectangle(Point(top_left_corner_x, top_left_corner_y), Point(bottom_right_corner_x, bottom_right_corner_y))



    
    # def moveSquare(self, squareverse):


    #     self.valid_directions = set(squareverse.valid_directions.keys())
    #     self.directions_already_tried = set()
    #     self.remaining_directions = set()
    #     self.selected_direction = None

    #     self.collision_detected = True
    #     self.number_of_collisions = 0
        
    #     self.child_squareverse_movement_cycles = 1

    #     self.body.setFill(self.body_color)
    #     self.body.setOutline(self.outline_color)
        

    #     if self.previous_direction == None:

    #         # print(f"\n\nSquare [{self.square_id}] hasn't moved so using child Squareverse") #debug
    #         self.child_squareverse_movement_cycles = 5

    #         while len(self.directions_already_tried) != len(self.valid_directions):

    #             self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
    #             # print(f"\n\nRemaining directions for Square [{self.square_id}] are [{self.remaining_directions}]") #debug

    #             self.selected_direction = self.child_squareverse.moveChildSquares(self.child_squareverse_movement_cycles, self)

    #             while self.selected_direction in self.directions_already_tried and len(self.directions_already_tried) <= len(self.valid_directions):

    #                 self.child_squareverse_movement_cycles = 1

    #                 self.selected_direction = self.child_squareverse.moveChildSquares(self.child_squareverse_movement_cycles, self)
                
    #             self.directions_already_tried.add(self.selected_direction)

    #             self.collision_detected = self.collisionCheck(squareverse, self.selected_direction)
    #             self.collision_detection_m = self.collision_detection_mongo(squareverse, self.selected_direction)

    #             if self.collision_detected == False:

    #                 # testing
    #                 self.body.p1.x = self.body.p1.x + squareverse.valid_directions[self.selected_direction]['x']
    #                 self.body.p1.y = self.body.p1.y + squareverse.valid_directions[self.selected_direction]['y']
    #                 self.body.p2.x = self.body.p2.x + squareverse.valid_directions[self.selected_direction]['x']
    #                 self.body.p2.y = self.body.p2.y  + squareverse.valid_directions[self.selected_direction]['y']

    #                 squareverse.window.move_by_id(self.tkinter_id, squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y']) # debug
                    
                    
    #                 # self.body._move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
    #                 # print(f"\n\nSquare [{self.square_id}] has moved [{self.selected_direction}]") #debug
                    
    #                 self.previous_direction = self.selected_direction

    #                 # self.previous_direction = None #testing

    #                 # updates global coordinates for Square
    #                 squareverse.square_positions.remove(self.current_coordinates)
    #                 self.current_coordinates = self.body.getCoordinates()
    #                 squareverse.square_positions.add(self.current_coordinates)

    #                 break
                    
    #             elif self.collision_detected == True:

    #                 pass
    #                 # directions_already_tried.add(selected_direction)
    #                 # print(f"Directions already tried are [{directions_already_tried}]") #D

    #                 # remaining_directions = valid_directions.difference(directions_already_tried)
    #                 # print(f"\n\nRemaining directions are [{remaining_directions}]")

    #         else:

    #             # print("There are no move valid directions remaining")
    #             self.body.setOutline("White")

    #     elif self.previous_direction != None:

    #         self.child_squareverse_movement_cycles = 1

    #         if self.child_squareverse.single_location != None:

    #             self.selected_direction = self.child_squareverse.single_location

    #         else:
                
    #             self.selected_direction = self.previous_direction

    #         self.directions_already_tried.add(self.selected_direction)

    #         self.collision_check = self.collisionCheck(squareverse, self.selected_direction)
    #         self.collision_check_m = self.collision_detection_mongo(squareverse, self.selected_direction) # testing

    #         if self.collision_check == False:

    #             self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
    #             # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction.upper()}]") #D

    #             # self.previous_direction = selected_direction
                
    #             squareverse.square_positions.remove(self.current_coordinates)
    #             self.current_coordinates = self.body.getCoordinates()
    #             squareverse.square_positions.add(self.current_coordinates)

    #             self.child_squareverse.moveChildSquares(self.child_squareverse_movement_cycles, self)

    #             # break
            
    #         elif self.collision_check == True:

    #             # self.directions_already_tried.add(self.selected_direction)
    #             # print(f"Directions already tried are [{directions_already_tried}]") #D

    #             self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
    #             # print(f"\n\nRemaining directions are [{remaining_directions}]")
                
    #             self.selected_direction = squareverse.valid_directions[self.selected_direction]['i']

    #             self.directions_already_tried.add(self.selected_direction)

    #             self.collision_check = self.collisionCheck(squareverse, self.selected_direction)

    #             if self.collision_check == False:

    #                 self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
    #                 # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

    #                 self.previous_direction = self.selected_direction
                    
    #                 squareverse.square_positions.remove(self.current_coordinates)
    #                 self.current_coordinates = self.body.getCoordinates()
    #                 squareverse.square_positions.add(self.current_coordinates)

    #                 self.child_squareverse.moveChildSquares(self.child_squareverse_movement_cycles, self)

    #                 # break

    #             # attempts to randomly move in any remaining direction
    #             elif self.collision_check == True:

    #                 self.child_squareverse_movement_cycles = 5

    #                 # self.directions_already_tried.add(self.selected_direction)
    #                 # print(f"Directions already tried are [{directions_already_tried}]") #D

    #                 self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
    #                 # print(f"\n\nRemaining directions are [{remaining_directions}]")

    #                 self.selected_direction = self.child_squareverse.moveChildSquares(self.child_squareverse_movement_cycles, self)

    #                 self.directions_already_tried.add(self.selected_direction)

    #                 self.collision_check = self.collisionCheck(squareverse, self.selected_direction)

    #                 if self.collision_check == False:

    #                     self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
    #                     # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

    #                     self.previous_direction = self.selected_direction
                        
    #                     squareverse.square_positions.remove(self.current_coordinates)
    #                     self.current_coordinates = self.body.getCoordinates()
    #                     squareverse.square_positions.add(self.current_coordinates)

    #                 elif self.collision_check == True:

    #                     # self.directions_already_tried.add(self.selected_direction)
    #                     # print(f"Directions already tried are [{directions_already_tried}]") #D

    #                     self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
    #                     # print(f"\n\nRemaining directions are [{remaining_directions}]")

    #                     # selects inverse of last direction tried as only 1 direction is remaining
    #                     self.selected_direction = squareverse.valid_directions[self.selected_direction]['i']

    #                     self.collision_check = self.collisionCheck(squareverse, self.selected_direction)

    #                     if self.collision_check == False:

                            
    #                         self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
    #                         # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

    #                         self.previous_direction = self.selected_direction
                            
    #                         squareverse.square_positions.remove(self.current_coordinates)
    #                         self.current_coordinates = self.body.getCoordinates()
    #                         squareverse.square_positions.add(self.current_coordinates)

    #                         # self.child_squareverse.moveChildSquares(self.child_squareverse_movement_cycles, self)

    #                     elif self.collision_check == True:

    #                         # print("There are no move valid directions remaining")
    #                         self.body.setOutline("White")
    
    
    
    
    
    
    
    def moveSquareChild(self, squareverse, square_p):
        

        self.valid_directions = set(squareverse.valid_directions.keys())
        self.directions_already_tried = square_p.directions_already_tried.copy() #inherits directions tried from parent Square
        # print(f"\n\nDirections already tried by Square parent are [{self.directions_already_tried}]") #debug
        self.remaining_directions = set()
        self.selected_direction = None
        # self.previous_direction = None #testing
        
        self.number_of_collisions = copy(square_p.number_of_collisions) #inherits number of collisions from parent Square
        self.collision_detected = True

        # resets color and outline for Square
        # self.body.setFill(self.body_color) #not required for child Square
        # self.body.setOutline(self.outline_color) #not required for child Square


        if self.previous_direction == None or self.previous_direction in self.directions_already_tried:

            # self.child_squareversehild.checkSquarePositions() #testing
            
            while len(self.directions_already_tried) != len(self.valid_directions):

                self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
                # print(f"\n\nRemaining directions for Square child [{self.square_id}] are {self.remaining_directions}") #debug

                self.selected_direction = choice(list(self.remaining_directions))

                self.directions_already_tried.add(self.selected_direction)

                self.collision_detected = self.collisionCheck(squareverse, self.selected_direction)

                if self.collision_detected == False:

                    self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                    # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")
                    
                    self.previous_direction = self.selected_direction

                    # updates global coordinates for Square
                    # print(f"\n\n{self.current_coordinates}")
                    squareverse.square_positions.remove(self.current_coordinates)
                    self.current_coordinates = self.body.getCoordinates()
                    squareverse.square_positions.add(self.current_coordinates)

                    break
                    
                elif self.collision_detected == True:

                    pass
                    # directions_already_tried.add(selected_direction)
                    # print(f"Directions already tried are [{directions_already_tried}]") #D

                    # remaining_directions = valid_directions.difference(directions_already_tried)
                    # print(f"\n\nRemaining directions are [{remaining_directions}]")

            else:

                pass
                # print("There are no move valid directions remaining")
                # self.body.setFill("Red")


        elif self.previous_direction != None and self.directions_already_tried != None:

            self.selected_direction = self.previous_direction

            self.directions_already_tried.add(self.selected_direction)

            self.collision_detected = self.collisionCheck(squareverse, self.selected_direction)

            if self.collision_detected == False:

                self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
            
                # updates global coordinates for Square
                squareverse.square_positions.remove(self.current_coordinates)
                self.current_coordinates = self.body.getCoordinates() 
                squareverse.square_positions.add(self.current_coordinates)
        
            elif self.collision_detected == True:

                if squareverse.valid_directions[self.selected_direction]['i'] not in self.directions_already_tried:

                    self.selected_direction = squareverse.valid_directions[self.selected_direction]['i']

                    self.directions_already_tried.add(self.selected_direction)

                    self.collision_detected = self.collisionCheck(squareverse, self.selected_direction)

                    if self.collision_detected == False:

                        self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                        # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

                        self.previous_direction = self.selected_direction
                        
                        # updates global coordinates for Square
                        squareverse.square_positions.remove(self.current_coordinates)
                        self.current_coordinates = self.body.getCoordinates()
                        squareverse.square_positions.add(self.current_coordinates)

                    elif self.collision_detected == True:

                        while len(self.directions_already_tried) != len(self.valid_directions):

                            self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
                            # print(f"\n\nRemaining directions for Square [{self.square_id}] are {remaining_directions}")

                            self.selected_direction = choice(list(self.remaining_directions))

                            self.directions_already_tried.add(self.selected_direction)

                            self.collision_detected = self.collisionCheck(squareverse, self.selected_direction)

                            if self.collision_detected == False:

                                self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                                # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")
                                
                                self.previous_direction = self.selected_direction

                                # updates global coordinates for Square
                                squareverse.square_positions.remove(self.current_coordinates)
                                self.current_coordinates = self.body.getCoordinates()
                                squareverse.square_positions.add(self.current_coordinates)

                                break
                                
                            elif self.collision_detected == True:

                                pass

                else:

                    while len(self.directions_already_tried) != len(self.valid_directions):

                        self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
                        # print(f"\n\nRemaining directions for Square [{self.square_id}] are {remaining_directions}")

                        self.selected_direction = choice(list(self.remaining_directions))

                        self.directions_already_tried.add(self.selected_direction)

                        self.collision_detected = self.collisionCheck(squareverse, self.selected_direction)

                        if self.collision_detected == False:

                            self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                            # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")
                            
                            self.previous_direction = self.selected_direction

                            # updates global coordinates for Square
                            squareverse.square_positions.remove(self.current_coordinates)
                            self.current_coordinates = self.body.getCoordinates()
                            squareverse.square_positions.add(self.current_coordinates)

                            break
                            
                        elif self.collision_detected == True:

                            pass


        elif self.previous_direction != None and self.directions_already_tried == None:

            self.selected_direction = self.previous_direction

            self.directions_already_tried.add(self.selected_direction)

            self.collision_detected = self.collisionCheck(squareverse, self.selected_direction)

            if self.collision_detected == False:

                self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
            
                # updates global coordinates for Square
                squareverse.square_positions.remove(self.current_coordinates)
                self.current_coordinates = self.body.getCoordinates() 
                squareverse.square_positions.add(self.current_coordinates)
        
            elif self.collision_detected == True:

            # self.directions_already_tried.add(selected_direction)
            # print(f"Directions already tried are [{directions_already_tried}]") #D

            # self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
            # print(f"\n\nRemaining directions are [{remaining_directions}]")
            
                self.selected_direction = squareverse.valid_directions[self.selected_direction]['i']

                self.directions_already_tried.add(self.selected_direction)

                self.collision_detected = self.collisionCheck(squareverse, self.selected_direction)

                if self.collision_detected == False:

                    self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                    # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

                    self.previous_direction = self.selected_direction
                    
                    # updates global coordinates for Square
                    squareverse.square_positions.remove(self.current_coordinates)
                    self.current_coordinates = self.body.getCoordinates()
                    squareverse.square_positions.add(self.current_coordinates)

                # attempts to randomly move in any remaining direction
                elif self.collision_detected == True:

                    while len(self.directions_already_tried) != len(self.valid_directions):

                        self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
                        # print(f"\n\nRemaining directions for Square [{self.square_id}] are {remaining_directions}")

                        self.selected_direction = choice(list(self.remaining_directions))

                        self.directions_already_tried.add(self.selected_direction)

                        self.collision_detected = self.collisionCheck(squareverse, self.selected_direction)

                        if self.collision_detected == False:

                            self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                            # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")
                            
                            self.previous_direction = self.selected_direction

                            # updates global coordinates for Square
                            squareverse.square_positions.remove(self.current_coordinates)
                            self.current_coordinates = self.body.getCoordinates()
                            squareverse.square_positions.add(self.current_coordinates)

                            break
                            
                        elif self.collision_detected == True:

                            self.selected_direction = squareverse.valid_directions[self.selected_direction]['i']

                            self.directions_already_tried.add(self.selected_direction)

                            self.collision_detected = self.collisionCheck(squareverse, self.selected_direction)

                            if self.collision_detected == False:

                                self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                                # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")
                            
                                self.previous_direction = self.selected_direction

                                # updates global coordinates for Square
                                squareverse.square_positions.remove(self.current_coordinates)
                                self.current_coordinates = self.body.getCoordinates()
                                squareverse.square_positions.add(self.current_coordinates)

                                break
                            
                            elif self.collision_detected == True:

                                pass








    def collisionCheck(self, squareverse, selected_direction):

        # creates an invisible clone of the Square's body ("Square's soul")
        square_soul = self.body.clone()
        # square_soul.setFill("Orange") #T
        # square_soul.draw(squareverse.window)
        
        # moves Square's soul to check for collisions
        square_soul.move(squareverse.valid_directions[selected_direction]['x'], squareverse.valid_directions[selected_direction]['y'])

        # checks current coordinates of Square's soul
        square_soul_coordinates = square_soul.getCoordinates()
        square_soul_coordinates_split = square_soul_coordinates.split(":")
        # print(f"\n\nCoordinates for the soul of Square [{self.square_id}] are [{square_soul_coordinates}] and split are {square_soul_coordinates_split}") #D
        
        # print("\n\nRunning logic for border detection!") #D
        if int(square_soul_coordinates_split[0]) < squareverse.squareverse_grid_spacing or int(square_soul_coordinates_split[1]) < squareverse.squareverse_grid_spacing or int(square_soul_coordinates_split[2]) > (squareverse.squareverse_size + squareverse.squareverse_grid_spacing) or int(square_soul_coordinates_split[3]) > (squareverse.squareverse_size + squareverse.squareverse_grid_spacing):

            collision_detected = True
            # del square_soul
            self.number_of_collisions = self.number_of_collisions + 1

            # print("\n\nCollision with Squareverse border detected") #D

            # return collision_detected

        elif square_soul_coordinates in squareverse.square_positions:

            collision_detected = True
            
            # del square_soul

            self.number_of_collisions = self.number_of_collisions + 1

            # print("\n\nCollision with another Square detected") #D

            # return collision_detected

        else:

            collision_detected = False
            
            # del square_soul

            # print("\n\nNo collisions detected") #D
            
            # return collision_detected

        del square_soul

        return collision_detected



    # def updateSquareCoordinates(self):


    def collision_detection_mongo(self, parent_squareverse, selected_direction):

        collision_detected, selected_direction_coordinates = parent_squareverse.mongo_client.collision_check_parent_squareverse(self, parent_squareverse, selected_direction)

        return collision_detected, selected_direction_coordinates




class SquareChild(ParentSquare):




    def __init__(self, square_id, squareverse_p):


        self.square_id = square_id
        self.body_color = color_rgb(
            max(0, min(255, randrange(0, 255))),
            max(0, min(255, randrange(0, 255))),
            max(0, min(255, randrange(0, 255)))
        )
        self.outline_color = self.body_color
        
        self.current_coordinates = None
        self.valid_directions = None
        self.previous_direction = None
        self.number_of_collisions = 0



    def drawSquareBody(self, squareverse_p, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):
        """Draw child square body with pygame."""
        self.body = Rectangle(Point(top_left_corner_x, top_left_corner_y), Point(bottom_right_corner_x, bottom_right_corner_y))
        
        # Set appearance for child squares
        self.body.setFill(self.body_color)
        self.body.setOutline(self.outline_color)
        
        # Draw and get ID, then update display
        self.tkinter_id = self.body.draw_square(squareverse_p.window, self)
        squareverse_p.window.update()

    def collision_detection_mongo_child(self, squareverse, selected_direction):

        collision_detected_mongo = squareverse.mongo_client.collision_check_child_squareverse(self, squareverse, selected_direction)

        return collision_detected_mongo
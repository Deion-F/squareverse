from time import sleep
from graphics import GraphWin, Point, Line, Rectangle, color_rgb
from random import randint, randrange, choice
from copy import copy
from mongo import Mongo
# import threading
# end of imports



class Squareverse():




    def __init__(self, squareverse_id, squareverse_name):

        
        self.squareverse_id = squareverse_id
        self.squareverse_name = squareverse_name
        self.squareverse_size = None
        self.squareverse_grid_spacing = None
        
        self.created_squares = []
        self.square_positions = set()

        self.mongo_client = Mongo()
       
        

        # print(f"\n\n***Squareverse Values***\nSquareverse ID: [{self.squareverse_id}]\nSquareverse Name: [{self.squareverse_name}]\nSquareverse Size: [{self.squareverse_size}px]\nSquareverse Grid Spacing: [{self.squareverse_grid_spacing}px]\nSquareverse Window Size: [{self.squareverse_window_size}px]") #debug

    

    def showSquareverseMenu(self):

    # valid_options = ["s", "d", "a", "m", "e"]

        while True:
        
            user_selection = input("\n\nPlease select what you want to do:\nSpawn a Square (s)\nDelete a Square (d)\nDelete all Squares (a)\nMove Squares (m)\nEnd the Squareverse simulation (e)\n\nOption: ")
            # assert user_selection in valid_options, "E: that was not a valid option!"

            if user_selection == "s":
                
                # draw_squares = True
                number_of_squares = input("\n\nEnter the number of Squares to spawn (m = max allowed, h = half max, q = quarter max): ")

                if number_of_squares == "m":
                    
                    number_of_squares = (self.max_number_of_squares - len(self.created_squares))
                
                elif number_of_squares == "h":
                    
                    number_of_squares = self.max_number_of_squares // 2
                
                elif number_of_squares == "q":
                    
                    number_of_squares = self.max_number_of_squares // 4
                
                else:
                    
                    pass

                self.createSquares(int(number_of_squares))

            elif user_selection == "d":
                
                pass
            
            elif user_selection == "a":
                
                pass
        
            elif user_selection == "m":
                
                self.moveAllSquares()

            else:
                
                
                self.mongo_client.delete_valid_directions()
                self.destroySquareverse()
                
                break
    
    
    def createSquareverseWindow(self, squareverse_size, squareverse_grid_spacing):
        
        
        self.window_background_color = color_rgb(97, 97, 97)
        self.grid_color = color_rgb(0, 0, 0)
        # self.grid_color =  self.window_background_color #testing

        self.squareverse_size = squareverse_size
        self.squareverse_grid_spacing = squareverse_grid_spacing
        self.squareverse_window_size = self.squareverse_size + (self.squareverse_grid_spacing * 2)
        self.max_number_of_squares = int(round((self.squareverse_size / self.squareverse_grid_spacing)) ** 2)
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

        

        self.mongo_client.insert_valid_directions(squareverse_grid_spacing)
        
        self.window = GraphWin(title = self.squareverse_name, width = self.squareverse_window_size, height = self.squareverse_window_size)
        
        self.window.setBackground(self.window_background_color)

        self.center_point = Point(self.center_point_coordinate, self.center_point_coordinate) #testing
        self.center_point.setFill("Orange") #testing


        self.createSquareverseGrid()


    
    def createSquareverseGrid(self):
        

        self.vertical_starting_point = self.squareverse_grid_spacing
        self.horizontal_starting_point = self.squareverse_grid_spacing
        self.number_of_lines = int(round((self.squareverse_size // self.squareverse_grid_spacing), 0) + 1)
        print(f"\n\n[{self.number_of_lines}] grid lines required") #debug
        # self.max_number_of_squares = int(round((self.squareverse_size / self.squareverse_grid_spacing)) ** 2)


        for _ in range(self.number_of_lines):

            # draws vertical lines
            first_point = Point(self.vertical_starting_point, self.squareverse_grid_spacing)
            second_point = Point(self.vertical_starting_point, (self.squareverse_size + self.squareverse_grid_spacing))

            self.vertical_line = Line(first_point, second_point)
           
            self.vertical_line.setOutline(self.grid_color)
            
            self.vertical_line.draw(self.window)

            self.vertical_starting_point = self.vertical_starting_point + self.squareverse_grid_spacing

            # draws horizontal lines
            first_point = Point(self.squareverse_grid_spacing, self.horizontal_starting_point)
            second_point = Point((self.squareverse_size + self.squareverse_grid_spacing), self.horizontal_starting_point)
            
            self.horizontal_line = Line(first_point, second_point)
            
            self.horizontal_line.setOutline(self.grid_color)
            
            self.horizontal_line.draw(self.window)

            self.horizontal_starting_point = self.horizontal_starting_point + self.squareverse_grid_spacing

        self.vertical_center_line = Line(Point(self.center_point_coordinate, self.top_border), Point(self.center_point_coordinate, self.bottom_border)) #testing
        
        self.horizontal_center_line = Line(Point(self.left_border, self.center_point_coordinate), Point(self.right_border, self.center_point_coordinate)) #testing

        self.vertical_center_line.setFill("Cyan") #testing
        self.horizontal_center_line.setFill("Cyan") #testing

        # self.vertical_center_line.draw(self.window) #testing
        # self.horizontal_center_line.draw(self.window) #testing
        # self.center_point.draw(self.window) #testing



    def createSquares(self, number_of_squares):

        # sets limits for where Squares can spawn in the Squareverse
        self.squareverse_max_xy = self.squareverse_size + self.squareverse_grid_spacing

        for _ in range(number_of_squares):
                       
            self.number_of_empty_grids = self.max_number_of_squares - len(self.created_squares)


            # prevents too many Squares from being created
            if self.number_of_empty_grids == 0:
                 
                print(f"\n\nThere are [{self.number_of_empty_grids}] empty grids remaining (no more grid space)") #debug

                break
                
            else:
            
                square_id = len(self.created_squares)

                square = Square(square_id, self)
                
                self.duplicate_square_check = True
            
                
                # needs to be optimized so that it doesn't slow down as more Squares are spawned
                while self.duplicate_square_check == True:
                    
                    top_left_corner_x = randrange(self.squareverse_grid_spacing, self.squareverse_max_xy, self.squareverse_grid_spacing)
                        
                    top_left_corner_y = randrange(self.squareverse_grid_spacing, self.squareverse_max_xy, self.squareverse_grid_spacing)

                    bottom_right_corner_x = top_left_corner_x + self.squareverse_grid_spacing
                    
                    bottom_right_corner_y = top_left_corner_y + self.squareverse_grid_spacing

                    # checks for duplicate Squares
                    self.duplicate_square_check = self.duplicateSquareCheck(square, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y)

            # adds coordinates to Square positions set for tracking
            self.square_positions.add(square.current_coordinates)
            self.mongo_client.insert_square_coordinates(square, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y)

            # adds Square to created Squares array
            self.created_squares.append(square)

            square.drawSquareBody(self, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y)

            # else:

            #     square.createSquareChild(top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y)


            # print(f"\n\nSquare {square.square_id} has been spawned at {square.coordinates}")
            # print(self.square_positions)



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
    
    
    
    def moveAllSquares(self):

        mouse_clicked = self.window.checkMouse()
       
        while mouse_clicked == None:

            for square in self.created_squares:
  
                square.moveSquare(self)
                    
                # mouse_clicked = self.window.checkMouse()
               
            mouse_clicked = self.window.checkMouse()



            



    # def moveSquareChildren(self, number_of_cycles, square_p):

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

    #         square_center = square.body.getCenterCoordinates()
    #         square_center_coordinates = square_center.split(':')

    #         if int(square_center_coordinates[0]) < self.center_point_coordinate:
    #             self.square_locations["left"] = self.square_locations["left"] + 1
    #         else:
    #             self.square_locations["right"] = self.square_locations["right"] + 1

    #         if int(square_center_coordinates[1]) < self.center_point_coordinate:
    #             self.square_locations["up"] = self.square_locations["up"] + 1
    #         else:
    #             self.square_locations["down"] = self.square_locations["down"] + 1

    #     # print(f"\n\nSquares left: {self.square_locations['left']}\n\nSquares right: {self.square_locations['right']}\n\nSquares up: {self.square_locations['up']}\n\nSquares down: {self.square_locations['down']}") #debug
    #     # print(max(self.square_locations, key=lambda key: self.square_locations[key]))



    # closes the Squareverse window
    def destroySquareverse(self):
        
        self.window.close()
        
        print(f"Ending the Squareverse simulation for {self.squareverse_name}!") #debug




class SquareverseChild(Squareverse):


    

    def __init__(self, squareverse_id, squareverse_name):

        super().__init__(squareverse_id, squareverse_name)
        


    def createSquareverseWindow(self, squareverse_size, squareverse_grid_spacing, window_background_color):

        self.window_background_color = window_background_color
        self.grid_color = color_rgb(255, 255, 255)

        self.squareverse_size = squareverse_size # TESTING
        self.squareverse_grid_spacing = squareverse_grid_spacing # TESTING
        self.max_number_of_squares = int(round((self.squareverse_size / self.squareverse_grid_spacing)) ** 2)
        # self.max_number_of_squares = 5 # TESTING
        self.top_border = squareverse_grid_spacing
        self.bottom_border = 300 + squareverse_grid_spacing
        self.left_border = squareverse_grid_spacing
        self.right_border = 300 + squareverse_grid_spacing
        self.center_point_coordinate = ((300 + squareverse_grid_spacing) + squareverse_grid_spacing) // 2
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



    def createSquares(self, number_of_squares):

        # sets limits for where Squares can spawn in the Squareverse
        self.squareverse_max_xy = self.squareverse_size + self.squareverse_grid_spacing

        for _ in range(number_of_squares):
                       
            square_id = len(self.created_squares)

            square = SquareChild(square_id, self)
            
            self.number_of_empty_grids = self.max_number_of_squares - len(self.created_squares)
            
            self.duplicate_square_check = True
            
            if self.number_of_empty_grids == 0:
                 
                print(f"\n\nThere are [{self.number_of_empty_grids}] empty grids remaining (no more grid space)") #debug

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
            self.created_squares.append(square)

            square.drawSquareBody(self, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y)



    def moveSquareChildren(self, number_of_cycles, square_p):

        for i in range(number_of_cycles):
            
            # print(f"\n\nMoved all children for Square [{square_p.square_id}] {i} times") #debug
            for square in self.created_squares:

                square.moveSquareChild(self, square_p)

        self.checkSquarePositions()

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








class Square():

    
    def __init__(self, square_id, squareverse_p):
        
        
        self.square_id = square_id
        self.body_color = color_rgb(randrange(0, 256), randrange(0, 256), randrange(0, 256))
        self.outline_color = self.body_color
        
        self.current_coordinates = None
        self.valid_directions = None
        self.previous_direction = None
        self.number_of_collisions = 0
        
        self.squareverse_c = SquareverseChild(self.square_id, f"{squareverse_p.squareverse_name} CHILD [{self.square_id}]")

        # create_window = False
        # draw_squares = False
        # self.squareverse_child.createSquareverseWindow(squareverse_parent.squareverse_size, squareverse_parent.squareverse_grid_spacing, create_window)
        # self.squareverse_child.createSquares((self.squareverse_child.max_number_of_squares // 2), draw_squares)



    def drawSquareBody(self, squareverse_p, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):

        self.body = Rectangle(Point(top_left_corner_x, top_left_corner_y), Point(bottom_right_corner_x, bottom_right_corner_y))
        
        self.body.setFill(self.body_color)

        self.body.setOutline(self.outline_color)
        
        self.body.draw(squareverse_p.window)
        
        self.squareverse_c.createSquareverseWindow(squareverse_p.squareverse_size, squareverse_p.squareverse_grid_spacing, self.body_color)

        self.squareverse_c.createSquares((self.squareverse_c.max_number_of_squares // 6))

        # self.squareverse_c.createSquares(10)

        # self.squareverse_child.createSquares(10, draw_squares) #testing

        # print(len(self.squareverse_child.square_positions)) #debug
        # print(self.squareverse_child.square_positions) #debug


        # print(f"\n\nTk ID for Square is [{tk_id}]") #D
        # print(f"Square body has been successfully drawn") #D



    # def createSquareChild(self, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):

    #     self.body = Rectangle(Point(top_left_corner_x, top_left_corner_y), Point(bottom_right_corner_x, bottom_right_corner_y))



    
    def moveSquare(self, squareverse):


        self.valid_directions = set(squareverse.valid_directions.keys())
        self.directions_already_tried = set()
        self.remaining_directions = set()
        self.selected_direction = None

        self.collision_detected = True
        self.number_of_collisions = 0
        
        self.child_squareverse_movement_cycles = 1

        self.body.setFill(self.body_color)
        self.body.setOutline(self.outline_color)
        

        if self.previous_direction == None:

            # print(f"\n\nSquare [{self.square_id}] hasn't moved so using child Squareverse") #debug
            self.child_squareverse_movement_cycles = 5

            while len(self.directions_already_tried) != len(self.valid_directions):

                self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
                # print(f"\n\nRemaining directions for Square [{self.square_id}] are [{self.remaining_directions}]") #debug

                self.selected_direction = self.squareverse_c.moveSquareChildren(self.child_squareverse_movement_cycles, self)

                while self.selected_direction in self.directions_already_tried and len(self.directions_already_tried) <= len(self.valid_directions):

                    self.child_squareverse_movement_cycles = 1

                    self.selected_direction = self.squareverse_c.moveSquareChildren(self.child_squareverse_movement_cycles, self)
                
                self.directions_already_tried.add(self.selected_direction)

                self.collision_detected = self.collisionCheck(squareverse, self.selected_direction)

                if self.collision_detected == False:

                    self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                    # print(f"\n\nSquare [{self.square_id}] has moved [{self.selected_direction}]") #debug
                    
                    self.previous_direction = self.selected_direction

                    # self.previous_direction = None #testing

                    # updates global coordinates for Square
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

                # print("There are no move valid directions remaining")
                self.body.setOutline("White")

        elif self.previous_direction != None:

            self.child_squareverse_movement_cycles = 1

            if self.squareverse_c.single_location != None:

                self.selected_direction = self.squareverse_c.single_location

            else:
                
                self.selected_direction = self.previous_direction

            self.directions_already_tried.add(self.selected_direction)

            self.collision_check = self.collisionCheck(squareverse, self.selected_direction)

            if self.collision_check == False:

                self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction.upper()}]") #D

                # self.previous_direction = selected_direction
                
                squareverse.square_positions.remove(self.current_coordinates)
                self.current_coordinates = self.body.getCoordinates()
                squareverse.square_positions.add(self.current_coordinates)

                self.squareverse_c.moveSquareChildren(self.child_squareverse_movement_cycles, self)

                # break
            
            elif self.collision_check == True:

                # self.directions_already_tried.add(self.selected_direction)
                # print(f"Directions already tried are [{directions_already_tried}]") #D

                self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
                # print(f"\n\nRemaining directions are [{remaining_directions}]")
                
                self.selected_direction = squareverse.valid_directions[self.selected_direction]['i']

                self.directions_already_tried.add(self.selected_direction)

                self.collision_check = self.collisionCheck(squareverse, self.selected_direction)

                if self.collision_check == False:

                    self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                    # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

                    self.previous_direction = self.selected_direction
                    
                    squareverse.square_positions.remove(self.current_coordinates)
                    self.current_coordinates = self.body.getCoordinates()
                    squareverse.square_positions.add(self.current_coordinates)

                    self.squareverse_c.moveSquareChildren(self.child_squareverse_movement_cycles, self)

                    # break

                # attempts to randomly move in any remaining direction
                elif self.collision_check == True:

                    self.child_squareverse_movement_cycles = 5

                    # self.directions_already_tried.add(self.selected_direction)
                    # print(f"Directions already tried are [{directions_already_tried}]") #D

                    self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
                    # print(f"\n\nRemaining directions are [{remaining_directions}]")

                    self.selected_direction = self.squareverse_c.moveSquareChildren(self.child_squareverse_movement_cycles, self)

                    self.directions_already_tried.add(self.selected_direction)

                    self.collision_check = self.collisionCheck(squareverse, self.selected_direction)

                    if self.collision_check == False:

                        self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                        # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

                        self.previous_direction = self.selected_direction
                        
                        squareverse.square_positions.remove(self.current_coordinates)
                        self.current_coordinates = self.body.getCoordinates()
                        squareverse.square_positions.add(self.current_coordinates)

                    elif self.collision_check == True:

                        # self.directions_already_tried.add(self.selected_direction)
                        # print(f"Directions already tried are [{directions_already_tried}]") #D

                        self.remaining_directions = self.valid_directions.difference(self.directions_already_tried)
                        # print(f"\n\nRemaining directions are [{remaining_directions}]")

                        # selects inverse of last direction tried as only 1 direction is remaining
                        self.selected_direction = squareverse.valid_directions[self.selected_direction]['i']

                        self.collision_check = self.collisionCheck(squareverse, self.selected_direction)

                        if self.collision_check == False:

                            
                            self.body.move(squareverse.valid_directions[self.selected_direction]['x'], squareverse.valid_directions[self.selected_direction]['y'])
                            # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

                            self.previous_direction = self.selected_direction
                            
                            squareverse.square_positions.remove(self.current_coordinates)
                            self.current_coordinates = self.body.getCoordinates()
                            squareverse.square_positions.add(self.current_coordinates)

                            # self.squareverse_c.moveSquareChildren(self.child_squareverse_movement_cycles, self)

                        elif self.collision_check == True:

                            # print("There are no move valid directions remaining")
                            self.body.setOutline("White")
    
    
    
    
    
    
    
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
        self.body.setFill(self.body_color) #not required for child Square
        self.body.setOutline(self.outline_color) #not required for child Square


        if self.previous_direction == None or self.previous_direction in self.directions_already_tried:

            # self.squareverse_child.checkSquarePositions() #testing
            
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




class SquareChild(Square):




    def __init__(self, square_id, squareverse_p):


        self.square_id = square_id
        self.body_color = color_rgb(randrange(0, 256), randrange(0, 256), randrange(0, 256))
        self.outline_color = self.body_color
        
        self.current_coordinates = None
        self.valid_directions = None
        self.previous_direction = None
        self.number_of_collisions = 0



    def drawSquareBody(self, squareverse_p, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):

        self.body = Rectangle(Point(top_left_corner_x, top_left_corner_y), Point(bottom_right_corner_x, bottom_right_corner_y))
        
        #everything after this can be commented out
        # self.body.setFill(self.body_color)

        # self.body.setOutline(self.outline_color)
        
        # self.body.draw(squareverse_p.window)
from time import sleep
from graphics import GraphWin, Point, Line, Rectangle, color_rgb
from random import randint, randrange, choice
# import threading
# end of imports



class Squareverse():


    squareverse_window_background_color = color_rgb(97, 97, 97)
    squareverse_grid_color = color_rgb(255, 255, 255)


    def __init__(self, squareverse_id, squareverse_name, squareverse_size, squareverse_grid_spacing):

        self.squareverse_id = squareverse_id
        self.squareverse_name = squareverse_name
        self.squareverse_size = squareverse_size
        self.squareverse_grid_spacing = squareverse_grid_spacing
        self.squareverse_window_size = self.squareverse_size + (self.squareverse_grid_spacing * 2)
        self.created_squares = []
        self.square_positions = set()
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

        # print(f"\n\n***Squareverse Values***\nSquareverse ID: [{self.squareverse_id}]\nSquareverse Name: [{self.squareverse_name}]\nSquareverse Size: [{self.squareverse_size}px]\nSquareverse Grid Spacing: [{self.squareverse_grid_spacing}px]\nSquareverse Window Size: [{self.squareverse_window_size}px]") #D
        
        self.createSquareverseWindow()

    

    def createSquareverseWindow(self):
        
        # creates Squareverse window, sets name & size
        self.window = GraphWin(title = self.squareverse_name, width = self.squareverse_window_size, height = self.squareverse_window_size)
        
        # sets background color of Squareverse using RGB
        self.window.setBackground(self.squareverse_window_background_color)
        # print(f"\n\nSquareverse window for has been successfully created for [{self.squareverse_name}]") #D
        
        # generates grid for Squareverse
        self.createSquareverseGrid()



    def createSquareverseGrid(self):
        
        # print(f"\n\nCreating Squareverse grid for [{self.squareverse_name}] using grid spacing of [{self.squareverse_grid_spacing}px]") #D

        vertical_starting_point = self.squareverse_grid_spacing
        horizontal_starting_point = self.squareverse_grid_spacing
        number_of_lines = int(round((self.squareverse_size / self.squareverse_grid_spacing), 0) + 1)
        # print(f"\n\n[{number_of_lines}] grid lines required") #D
        
        self.max_number_of_squares = int(round((self.squareverse_size / self.squareverse_grid_spacing)) ** 2)
        # print(f"[{self.max_number_of_squares}] maximum Squares can be created") #D

        for _ in range(number_of_lines):

            # creates vertical lines
            first_point = Point(vertical_starting_point, self.squareverse_grid_spacing)
            second_point = Point(vertical_starting_point, (self.squareverse_size + self.squareverse_grid_spacing))
            # print(f"\n\nCoordinates for grid line [first point - {first_point}] [second point - {second_point}]") #D
            vertical_line = Line(first_point, second_point)
           
            vertical_line.setOutline(self.squareverse_grid_color)
            
            vertical_line.draw(self.window)

            vertical_starting_point = vertical_starting_point + self.squareverse_grid_spacing

            # creates horizontal lines
            first_point = Point(self.squareverse_grid_spacing, horizontal_starting_point)
            second_point = Point((self.squareverse_size + self.squareverse_grid_spacing), horizontal_starting_point)
            horizontal_line = Line(first_point, second_point)
            
            horizontal_line.setOutline(self.squareverse_grid_color)
            
            horizontal_line.draw(self.window)

            horizontal_starting_point = horizontal_starting_point + self.squareverse_grid_spacing

        # print(f"\n\nSquareverse grid has been successfully created for [{self.squareverse_name}]") #D



    def createSquares(self, number_of_squares):

        # sets limits for where Squares can spawn in the Squareverse
        squareverse_max_xy = self.squareverse_size + self.squareverse_grid_spacing

        # creates number of Squares provided by number_of_squares
        for _ in range(number_of_squares):
            
            square = Square()
            number_of_empty_grids = self.max_number_of_squares - len(self.created_squares)
            duplicate_square_check = True
            
            if number_of_empty_grids == 0:
                 
                # print(f"\n\nThere are [{number_of_empty_grids}] empty grids remaining (no more grid space)") #D

                break
                
            else:
            
                while duplicate_square_check == True:
                    
                    top_left_corner_x = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)
                        
                    top_left_corner_y = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)

                    bottom_right_corner_x = top_left_corner_x + self.squareverse_grid_spacing
                    
                    bottom_right_corner_y = top_left_corner_y + self.squareverse_grid_spacing

                    # checks for duplicate Squares
                    duplicate_square_check = self.duplicateSquareCheck(square, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y)


            # draws the Square if there are no duplicates
            square.drawSquareBody(self.window, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y)
            
            # defines the Square ID based on the array index            
            square.square_id = len(self.created_squares)

            # adds coordinates to Square positions set for tracking
            self.square_positions.add(square.coordinates)

            # adds Square to created Squares array
            self.created_squares.append(square)


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

            square.coordinates = square_coordinates

            return duplicate_square
    
    
    
    def moveAllSquares(self):

        mouse_clicked = self.window.checkMouse()
       
        while mouse_clicked == None:

            for square in self.created_squares:

                if mouse_clicked == None:
  
                    square.moveSquare(self)
                    
                    mouse_clicked = self.window.checkMouse()
               
                else:
                    
                    break



    # closes the Squareverse window
    def destroySquareverse(self):
        
        self.window.close()
        print(f"Ending the Squareverse simulation for {self.squareverse_name}!")







# ---CLASSLESS FUNCTIONS--- 



def createSquareverse():

    squareverse_id = randint(1, 100)
    squareverse_name = f"Squareverse[{squareverse_id}]"
    squareverse_size = input("\n\nSquareverse size (1 - 10): ") # determines Squareverse size by multiplying provided value by 100

    if len(squareverse_size) == 0:
        
        squareverse_size = 8 # default value for Squareverse size
    
    elif int(squareverse_size) > 10 or int(squareverse_size) < 1:

        print("\n\nPlease choose a value within the provided range")
    
    else:
        
        pass

    squareverse_size = (int(squareverse_size) * 100) # calculates actual Squareverse window size
    valid_grid_sizes = [i for i in range(10, ((squareverse_size // 10) + 1)) if squareverse_size % i == 0]
    squareverse_grid_spacing = choice(valid_grid_sizes)
    squareverse = Squareverse(squareverse_id, squareverse_name, squareverse_size, squareverse_grid_spacing) # creates a Squareverse
    
    print(f"\n\n[{squareverse_name}] has been successfully created") #D



    return squareverse
    


def showMenu(squareverse):

    valid_options = ["s", "d", "a", "m", "e"]

    while True:
       
        user_selection = input("\n\nPlease select what you want to do:\nSpawn a Square (s)\nDelete a Square (d)\nDelete all Squares (a)\nMove Squares (m)\nEnd the Squareverse simulation (e)\n\nOption: ")
        assert user_selection in valid_options, "E: that was not a valid option!"

        if user_selection == "s":
            
            number_of_squares = input("\n\nEnter the number of Squares to spawn (m = max allowed, h = half max, q = quarter max): ")

            if number_of_squares == "m":
                
                number_of_squares = (squareverse.max_number_of_squares - len(squareverse.created_squares))
            
            elif number_of_squares == "h":
                
                number_of_squares = squareverse.max_number_of_squares // 2
            
            elif number_of_squares == "q":
                
                number_of_squares = squareverse.max_number_of_squares // 4
            
            else:
                
                pass

            squareverse.createSquares(int(number_of_squares))

        elif user_selection == "d":
            pass
        elif user_selection == "a":
            pass
        elif user_selection == "m":
            
            # default_duration = 10
            # duration = input(f"Enter a duration for movement (default {default_duration}): ")
            
            # if duration == "" or duration.isnumeric == False:
            #     duration = default_duration

            # print(f"Moving Squares...")
            
            squareverse.moveAllSquares()

        else:
            squareverse.destroySquareverse()
            break





class Square():

    
    def __init__(self):
        
        
        self.square_id = 0
        self.body_color = color_rgb(255, 255, 255)
        self.outline_color = color_rgb(0, randrange(0, 256), randrange(0, 256))
        self.coordinates = None
        self.valid_directions = None
        self.previous_direction = None
        self.number_of_collisions = 0



    def drawSquareBody(self, squareverse_window, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):

        self.body = Rectangle(Point(top_left_corner_x, top_left_corner_y), Point(bottom_right_corner_x, bottom_right_corner_y))
        
        self.body.setFill(self.body_color)

        self.body.setOutline(self.outline_color)
        
        self.body.draw(squareverse_window)

        # print(f"\n\nTk ID for Square is [{tk_id}]") #D
        # print(f"Square body has been successfully drawn") #D



    def moveSquare(self, squareverse):
        

        # list_of_squares = squareverse.created_squares
        # number_of_squares = len(squareverse.created_squares)
        # square_coordinates = self.coordinates.split(":")
        
        valid_directions = set(squareverse.valid_directions.keys())
        selected_direction = None
        directions_already_tried = set()
        remaining_directions = set()
        collision_detected = True
        self.number_of_collisions = 0

        # print(f"\n\nCoordinates of Square [{self.square_id}] before moving are {self.coordinates}") #D
        # print(f"Valid directions to move in are {valid_directions}") #D
        

        # resets color and outline for Square
        self.body.setFill(self.body_color)
        self.body.setOutline(self.outline_color)
        # print(f"\n\nColor and outline of Square [{self.square_id}] has been reset to [{self.body_color}:{self.outline_color}]") #D
        
        # checks if Square moved last cycle
        if self.previous_direction == None:

            # print(f"\n\nSquare {self.square_id} did not move last cycle so picking a random direction") #D
            
            while self.number_of_collisions < 4:

                remaining_directions = valid_directions.difference(directions_already_tried)
                # print(f"\n\nRemaining directions for Square [{self.square_id}] are {remaining_directions}")

                selected_direction = choice(list(remaining_directions))

                directions_already_tried.add(selected_direction)

                collision_detected = self.collisionCheck(squareverse, selected_direction)

                if collision_detected == False:

                    self.body.move(squareverse.valid_directions[selected_direction]['x'], squareverse.valid_directions[selected_direction]['y'])
                    # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")
                    
                    self.previous_direction = selected_direction

                    squareverse.square_positions.remove(self.coordinates)
                
                    self.coordinates = self.body.getCoordinates()
                
                    squareverse.square_positions.add(self.coordinates)

                    break
                    
                elif collision_detected == True:

                    pass
                    # directions_already_tried.add(selected_direction)
                    # print(f"Directions already tried are [{directions_already_tried}]") #D

                    # remaining_directions = valid_directions.difference(directions_already_tried)
                    # print(f"\n\nRemaining directions are [{remaining_directions}]")

            else:

                # print("There are no move valid directions remaining")
                self.body.setOutline("Red")

        elif self.previous_direction != None:

            # attempts to contine moving in the previous direction first
            selected_direction = self.previous_direction

            collision_check = self.collisionCheck(squareverse, selected_direction)

            if collision_check == False:

                self.body.move(squareverse.valid_directions[selected_direction]['x'], squareverse.valid_directions[selected_direction]['y'])
                # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction.upper()}]") #D

                # self.previous_direction = selected_direction
                
                squareverse.square_positions.remove(self.coordinates)
                
                self.coordinates = self.body.getCoordinates()
                
                squareverse.square_positions.add(self.coordinates)

                # break
            
            # attempts to move in the inverse direction ('i') next
            elif collision_check == True:

                directions_already_tried.add(selected_direction)
                # print(f"Directions already tried are [{directions_already_tried}]") #D

                remaining_directions = valid_directions.difference(directions_already_tried)
                # print(f"\n\nRemaining directions are [{remaining_directions}]")
                
                selected_direction = squareverse.valid_directions[selected_direction]['i']

                collision_check = self.collisionCheck(squareverse, selected_direction)

                if collision_check == False:

                    self.body.move(squareverse.valid_directions[selected_direction]['x'], squareverse.valid_directions[selected_direction]['y'])
                    # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

                    self.previous_direction = selected_direction
                    
                    squareverse.square_positions.remove(self.coordinates)
                    
                    self.coordinates = self.body.getCoordinates()
                    
                    squareverse.square_positions.add(self.coordinates)

                    # break

                # attempts to randomly move in any remaining direction
                elif collision_check == True:

                    directions_already_tried.add(selected_direction)
                    # print(f"Directions already tried are [{directions_already_tried}]") #D

                    remaining_directions = valid_directions.difference(directions_already_tried)
                    # print(f"\n\nRemaining directions are [{remaining_directions}]")

                    selected_direction = choice(list(remaining_directions))

                    collision_check = self.collisionCheck(squareverse, selected_direction)

                    if collision_check == False:

                        self.body.move(squareverse.valid_directions[selected_direction]['x'], squareverse.valid_directions[selected_direction]['y'])
                        # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

                        self.previous_direction = selected_direction
                        
                        squareverse.square_positions.remove(self.coordinates)
                        
                        self.coordinates = self.body.getCoordinates()
                        
                        squareverse.square_positions.add(self.coordinates)

                    elif collision_check == True:

                        directions_already_tried.add(selected_direction)
                        # print(f"Directions already tried are [{directions_already_tried}]") #D

                        remaining_directions = valid_directions.difference(directions_already_tried)
                        # print(f"\n\nRemaining directions are [{remaining_directions}]")

                        selected_direction = choice(list(remaining_directions))

                        collision_check = self.collisionCheck(squareverse, selected_direction)

                        if collision_check == False:

                            self.body.move(squareverse.valid_directions[selected_direction]['x'], squareverse.valid_directions[selected_direction]['y'])
                            # print(f"\n\nSquare [{self.square_id}] has moved [{selected_direction}]")

                            self.previous_direction = selected_direction
                            
                            squareverse.square_positions.remove(self.coordinates)
                            
                            self.coordinates = self.body.getCoordinates()
                            
                            squareverse.square_positions.add(self.coordinates)

                        elif collision_check == True:

                            # print("There are no move valid directions remaining")
                            self.body.setOutline("Red")



    def collisionCheck(self, squareverse, selected_direction):

        # creates an invisible clone of the Square's body ("Square's soul")
        square_soul = self.body.clone()
        square_soul.setFill("Orange") #T
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


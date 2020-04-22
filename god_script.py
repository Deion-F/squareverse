from time import sleep
from graphics import GraphWin, Point, Line, Rectangle, color_rgb
from random import randint, randrange, choice
# import threading
# end of imports

#COMMENT LEGEND
# Code for debugging - #D
# Code for providing information - #I
# Temporary code used for testing - #T


class Squareverse():


    squareverse_window_background_color = color_rgb(97, 97, 97)
    squareverse_grid_color = color_rgb(0, 255, 255)


    def __init__(self, squareverse_id, squareverse_name, squareverse_size, squareverse_grid_spacing):
        
        self.squareverse_id = squareverse_id
        self.squareverse_name = squareverse_name
        self.squareverse_size = squareverse_size
        self.squareverse_grid_spacing = squareverse_grid_spacing
        self.squareverse_window_size = self.squareverse_size + (self.squareverse_grid_spacing * 2)
        self.created_squares = []
        self.square_positions = set()
        self.valid_directions = {"up": (0, (self.squareverse_grid_spacing * -1)), "down": (0, self.squareverse_grid_spacing), "left": ((self.squareverse_grid_spacing * -1), 0),"right": (self.squareverse_grid_spacing, 0)}
        
        print(f"\n\n***Squareverse Values***\nSquareverse ID: [{self.squareverse_id}]\nSquareverse Name: [{self.squareverse_name}]\nSquareverse Size: [{self.squareverse_size}px]\nSquareverse Grid Spacing: [{self.squareverse_grid_spacing}px]\nSquareverse Window Size: [{self.squareverse_window_size}px]") #D
        
        self.createSquareverseWindow()

    

    def createSquareverseWindow(self):
        
        # creates Squareverse window, sets name & size
        self.window = GraphWin(title = self.squareverse_name, width = self.squareverse_window_size, height = self.squareverse_window_size)
        
        # sets background color of Squareverse using RGB
        self.window.setBackground(self.squareverse_window_background_color)

        print(f"\n\nSquareverse window for has been successfully created for [{self.squareverse_name}]") #D
        
        # generates grid for squareverse
        self.createSquareverseGrid()



    def createSquareverseGrid(self):
        
        print(f"\n\nCreating Squareverse grid for [{self.squareverse_name}] using grid spacing of [{self.squareverse_grid_spacing}px]") #D

        vertical_starting_point = self.squareverse_grid_spacing
        horizontal_starting_point = self.squareverse_grid_spacing
        number_of_lines = int(round((self.squareverse_size / self.squareverse_grid_spacing), 0) + 1)
        self.max_number_of_squares = int(round((self.squareverse_size / self.squareverse_grid_spacing)) ** 2)
        
        print(f"\n\n[{number_of_lines}] grid lines required") #D
        print(f"[{self.max_number_of_squares}] maximum Squares can be created") #D

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

        print(f"\n\nSquareverse grid has been successfully created for [{self.squareverse_name}]") #D



    def createSquares(self, number_of_squares):

        # sets limits for where Squares can spawn in the Squareverse
        squareverse_max_xy = self.squareverse_size + self.squareverse_grid_spacing

        # creates number of Squares provided by number_of_squares
        for _ in range(number_of_squares):
            
            square = Square()
            number_of_existing_squares = len(self.created_squares)
            number_of_empty_grids = self.max_number_of_squares - number_of_existing_squares
            duplicate_square_check = True
            # print(f"\n\n[{number_of_empty_grids}] empty grids remaining before spawing Square | Max number of Squares [{self.max_number_of_squares}] | Length of created Squares [{len(self.created_squares)}]") #D
            
            if number_of_empty_grids == 0:
                 
                print(f"\n\nThere are [{number_of_empty_grids}] empty grids remaining (no more grid space)") #D

                break

            # elif number_of_existing_squares == 0:
                
            #     top_left_corner_x = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)
                
            #     top_left_corner_y = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)

            #     bottom_right_corner_x = top_left_corner_x + self.squareverse_grid_spacing
                
            #     bottom_right_corner_y = top_left_corner_y + self.squareverse_grid_spacing

            #     center_point = str((top_left_corner_x + bottom_right_corner_x) // 2) + ":" + str((top_left_corner_y + bottom_right_corner_y) // 2)
                
            else:
            
                while duplicate_square_check == True:
                    
                    top_left_corner_x = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)
                        
                    top_left_corner_y = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)

                    bottom_right_corner_x = top_left_corner_x + self.squareverse_grid_spacing
                    
                    bottom_right_corner_y = top_left_corner_y + self.squareverse_grid_spacing


                    duplicate_square_check = self.duplicateSquareCheck(square, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y)


            # draws the Square
            square.drawSquareBody(self.window, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y)
                
                
                
            #     while grid_occupied == True:
                
            #         print(f"\n\nCreating random coordinates for Square top left corner") #D
            #         # print(f"List of Squares: [{self.created_squares}]") #D
                    
            #         top_left_corner_x = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)
                    
            #         top_left_corner_y = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)

            #         for square in self.created_squares:
                        
            #             if square.top_left_corner_x == top_left_corner_x and square.top_left_corner_y == top_left_corner_y:
                            
            #                 print(f"\n\nSquare [{square.square_id}] already exists in this location!") #D
            #                 grid_occupied = True
                            
            #                 break

            #             else:
                            
            #                 grid_occupied = False


            # bottom_right_corner_x = top_left_corner_x + self.squareverse_grid_spacing
            # bottom_right_corner_y = top_left_corner_y + self.squareverse_grid_spacing

            
            
            # defines the Square ID based on the array index            
            square.square_id = len(self.created_squares)

            # adds center coordinates of Square to Square positions set for tracking
            self.square_positions.add(square.center_coordinates)

            # adds Square to created Squares array
            self.created_squares.append(square)



            print(f"\n\nSquare {square.square_id} has been spawned at {square.center_coordinates}")
            print(self.square_positions)

            # print(f"\n\nSquare [{(square.square_id}] has been spawned at: [top left corner - {(self.created_squares[len(self.created_squares) - 1]).top_left_corner_x}:{(self.created_squares[len(self.created_squares) - 1]).top_left_corner_y}] [bottom right corner - {(self.created_squares[len(self.created_squares) - 1]).bottom_right_corner_x}:{(self.created_squares[len(self.created_squares) - 1]).bottom_right_corner_y}] [center - {(self.created_squares[len(self.created_squares) - 1]).coordinates}]") #D



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
    def destroy_squareverse(self):
        
        self.window.close()
        print(f"Ending the Squareverse simulation for {self.squareverse_name}!")




    def duplicateSquareCheck(self, square, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):

        # square_corner_coordinates = f"{top_left_corner_x}:{top_left_corner_y}:{bottom_right_corner_x}:{bottom_right_corner_y}"

        square_center_coordinates = str((top_left_corner_x + bottom_right_corner_x) / 2) + ":" +  str((top_left_corner_y + bottom_right_corner_y) / 2)
        
        
        if square_center_coordinates in self.square_positions:

            duplicate_square = True

            print(f"\n\nA Square already exists @ {square_center_coordinates}") #D
            

            return duplicate_square

            
        
        else:

            duplicate_square = False

            # square.corner_coordinates = f"{top_left_corner_x}:{top_left_corner_y}:{bottom_right_corner_x}:{bottom_right_corner_y}"

            square.center_coordinates = square_center_coordinates


            return duplicate_square


# ---CLASSLESS FUNCTIONS--- 



def createSquareverse():

    squareverse_id = randint(1, 100)
    squareverse_name = f"Squareverse [{squareverse_id}]"
    
    # determines Squareverse size by multiplying provided value by 100
    squareverse_size = input("\n\nSquareverse size (1 - 10): ")

    if len(squareverse_size) == 0:
        
        # default value for Squareverse size
        squareverse_size = 8 
    
    elif squareverse_size > 10:

        print("\n\nPlease choose a value within the provided range")
    
    else:
        
        pass

    squareverse_size = (int(squareverse_size) * 100) # calculates actual Squareverse window size

    print(f"\n\nCalculating possible grid sizes for [{squareverse_size}px]")

    valid_grid_sizes = [i for i in range(10, ((squareverse_size // 10) + 1)) if squareverse_size % i == 0]
    print(f"\n\nList of valid grid sizes are [{valid_grid_sizes}]")
    
    squareverse_grid_spacing = choice(valid_grid_sizes)
    
    squareverse = Squareverse(squareverse_id, squareverse_name, squareverse_size, squareverse_grid_spacing)
    
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

            print(f"Moving Squares...")
            
            squareverse.moveAllSquares()

        else:
            squareverse.destroy_squareverse()
            break





class Square():

    
    def __init__(self):
        
        
        # self.top_left_corner_x = top_left_corner_x
        # self.top_left_corner_y = top_left_corner_y
        # self.bottom_right_corner_x = bottom_right_corner_x
        # self.bottom_right_corner_y = bottom_right_corner_y
        
        self.body_color = color_rgb(0, randrange(0, 256), randrange(0, 256)) #testing random Square color
        # self.square_id = 0
        self.center_coordinates = ""
        self.valid_directions = None
        self.previous_direction = None

        # self.drawSquare()



    def drawSquareBody(self, squareverse_window, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):

        self.body = Rectangle(Point(top_left_corner_x, top_left_corner_y), Point(bottom_right_corner_x, bottom_right_corner_y))
        
        self.body.setFill(self.body_color)
        
        self.body.draw(squareverse_window)

        # self.center_coordinates = center_point




    def moveSquare(self, squareverse):
        
        list_of_squares = squareverse.created_squares
        number_of_squares = len(squareverse.created_squares)
        square_center_coordinates = self.center_coordinates.split()
        print(f"Center coordinates for Square {self.square_id} are {square_center_coordinates}")
        
        self.previous_direction = None
        
        
        self.valid_directions = squareverse.valid_directions
        print(f"\n\nValid directions are [{self.valid_directions}]") #D


        # squareverse_size = squareverse.squareverse_size
        # squareverse_grid_spacing = squareverse.squareverse_grid_spacing
        # list_of_squares = squareverse.created_squares
        # movement_dx = 0
        # movement_dy = 0
        # list_of_coordinates = []
        # collision_detected = True
        # number_of_collisions = 0
        # directions_already_tried = set()
        
        # direction_opposites = {"up": "down", "down": "up", "left": "right", "right": "left"}
        


        # UPDATED MOVING LOGIC
        
        # reset Square color
        self.body.setFill(self.body_color)

        print("\n\nResetting color of Square")
        
        # logic if Square didn't move last cycle
        if self.previous_direction == None:
            
            # #  builds the list of Square center point coordinates (Point objects) for all Squares that currently exist (including this Square)
            # for square in squareverse.created_squares:
                
            #     coordinate_ x = square.coordinate.getX()
            #     coordinate_ y = 
            #     coordinates = square.coordinates
            #     list_of_coordinates.append(coordinates)
            # # print("\n\nList of Square coordinates: " + str(list_of_coordinates)) # debug


            for direction in self.valid_directions.items():

                # selected_direction = direction
                # direction_movement = self.valid_directions[direction]

                # selected_direction = direction[0]
                # direction_movement = direction[1]
                
                print(f"\n\nRunning collision check for the direction[{direction}]") #D
                
                collision_check = self.collisionCheck(squareverse, direction)

                if collision_check == False:
                    
                    # selected_direction = selected_direction
                    break

                else:

                    # del self.valid_directions[selected_direction]
                    # self.valid_directions.pop(selected_direction)
                    print(self.valid_directions)


            self.body.move(direction[0][0], direction[0][1])
            self.previous_direction = direction[0]

        else:

            pass

















    def collisionCheck(self, squareverse, direction):

        # creates an invisible clone of the Square's body ("Square's soul")
        square_soul = self.body.clone()
        square_soul.setOutline("Orange") #T
        
        # moves Square's soul to check for collisions
        square_soul.move(direction[0][0], direction[0][1])

        # checks current coordinates of Square's soul
        square_soul_coordinates = square_soul.getCenter()
        square_soul_coordinates_2 = f"{square_soul_coordinates.getX()}:{square_soul_coordinates.getY()} "

        print(f"\n\nCoordinates of the soul for Square [{self.square_id}] are [X: {square_soul_coordinates.getX()} Y: {square_soul_coordinates.getY()}]")

        print("\n\nRunning logic for border detection!") #D

        if square_soul_coordinates.getX() <= squareverse.squareverse_grid_spacing or square_soul_coordinates.getY() <= squareverse.squareverse_grid_spacing or square_soul_coordinates.getX() >= (squareverse.squareverse_size + squareverse.squareverse_grid_spacing) or square_soul_coordinates.getY() >= (squareverse.squareverse_size + squareverse.squareverse_grid_spacing):

            collision_detected = True
            del square_soul

            print("\n\nCollision with Squareverse border detected") #D

            return collision_detected

        elif square_soul_coordinates_2 in squareverse.square_positions:

            collision_detected = True
            del square_soul

            print("\n\nCollision with another Square detected") #D

            return collision_detected

        else:

            collision_detected = False
            del square_soul

            print("No collisions detected")
            return collision_detected


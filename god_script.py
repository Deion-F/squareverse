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
        self.directions = {"up": (0, (self.squareverse_grid_spacing * -1)), "down": (0, self.squareverse_grid_spacing), "left": ((self.squareverse_grid_spacing * -1), 0),"right": (0, self.squareverse_grid_spacing)}
        
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

        # creates number of Squares provided by number_of_squares
        for _ in range(number_of_squares):
            
            grid_occupied = True
            number_of_empty_grids = (self.max_number_of_squares - len(self.created_squares))
            # print(f"\n\n[{number_of_empty_grids}] empty grids remaining before spawing Square | Max number of Squares [{self.max_number_of_squares}] | Length of created Squares [{len(self.created_squares)}]") #D
            squareverse_max_xy = (self.squareverse_size + self.squareverse_grid_spacing)

            if number_of_empty_grids == 0 :
                 
                print(f"\n\nThere are [{number_of_empty_grids}] empty grids remaining (no more grid space)") #D

                break

            elif len(self.created_squares) == 0:
                
                top_left_corner_x = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)
                top_left_corner_y = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)
                
            else:
            
                while number_of_empty_grids > 0 and grid_occupied == True:
                
                    # while grid_occupied == True:
                    print(f"\n\nCreating random coordinates for Square top left corner") #D
                    # print(f"List of Squares: [{self.created_squares}]") #D
                    top_left_corner_x = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)
                    top_left_corner_y = randrange(self.squareverse_grid_spacing, squareverse_max_xy, self.squareverse_grid_spacing)

                    for square in self.created_squares:
                        
                        if square.top_left_corner_x == top_left_corner_x and square.top_left_corner_y == top_left_corner_y:
                            
                            print(f"\n\nSquare [{square.square_id}] already exists in this location!") #D
                            grid_occupied = True
                            
                            break

                        else:
                            
                            grid_occupied = False




            bottom_right_corner_x = top_left_corner_x + self.squareverse_grid_spacing
            bottom_right_corner_y = top_left_corner_y + self.squareverse_grid_spacing

            square = Square(top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y, self.window)

            # adds Square object to array for Squareverse
            self.created_squares.append(square)

            # defines the Square ID based on the array index            
            (self.created_squares[len(self.created_squares) - 1]).square_id = len(self.created_squares) - 1


            print(f"\n\nSquare [{(self.created_squares[len(self.created_squares) - 1]).square_id}] has been spawned at: [top left corner - {(self.created_squares[len(self.created_squares) - 1]).top_left_corner_x}:{(self.created_squares[len(self.created_squares) - 1]).top_left_corner_y}] [bottom right corner - {(self.created_squares[len(self.created_squares) - 1]).bottom_right_corner_x}:{(self.created_squares[len(self.created_squares) - 1]).bottom_right_corner_y}] [center - {(self.created_squares[len(self.created_squares) - 1]).coordinates}]") #D



    def moveSquares(self):

        
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



# ---CLASSLESS FUNCTIONS--- 



def createSquareverse():
    
    #TO-DO
    # figure out why Squareverse grid breaks when grid spacing is too big (e.g. 90px)
    # add logic to create Squareverse size based on number system (e.g. size 4 = 400px)

    squareverse_id = randint(1, 100)
    squareverse_name = "Squareverse " + str(squareverse_id)
    squareverse_size = input("\n\nSquareverse Size (1 - 10): ")

    # print(f"\n\nAmount of values provided for Squareverse size are [{len(squareverse_size)}] and numeric check is [{squareverse_size.isnumeric()}]") #D
    # assert len(squareverse_size) == 0 or squareverse_size.isnumeric() == True, f"'{squareverse_size}' is not a number"

    if len(squareverse_size) == 0:
        squareverse_size = 8
    else:
        pass

    squareverse_size = (int(squareverse_size) * 100) # calculates actual Squareverse window size

    print(f"Calculating possible grid sizes for [{squareverse_size}px]")

    valid_grid_sizes = [i for i in range(10, ((squareverse_size // 10) + 1)) if squareverse_size % i == 0]
    print(f"\n\nList of valid grid sizes are [{valid_grid_sizes}]")
    
    squareverse_grid_spacing = choice(valid_grid_sizes)
    
    # squareverse_grid_spacing = input("\n\nGrid Spacing (default - random): ")

    # print(f"\n\nAmount of values provided for Squareverse grid spacing are [{len(squareverse_grid_spacing)}] and numeric check is [{squareverse_grid_spacing.isnumeric()}]") #D
    # assert len(squareverse_grid_spacing) == 0 or squareverse_grid_spacing.isnumeric() == True, f"'{squareverse_grid_spacing}' is not a number"

    # if len(squareverse_grid_spacing) == 0:
    #     # squareverse_grid_spacing = 40
    #     squareverse_grid_spacing = randrange(10, 100, 5)
    #     print(f"\n\nRandomly chosen grid spacing is [{squareverse_grid_spacing}px]") #D
    # else:
    #     pass

    # creates Squareverse using provided values
    squareverse = Squareverse(squareverse_id, squareverse_name, int(squareverse_size), int(squareverse_grid_spacing))
    print(f"\n\n[{squareverse.squareverse_name}] has been successfully created") #D


    return squareverse
    




def showMenu(squareverse):

    valid_options = ["s", "d", "a", "m", "e"]

    while True:
       
        user_selection = input("\n\nPlease select what you want to do:\nSpawn a Square (s)\nDelete a Square (d)\nDelete all Squares (a)\nMove Squares (m)\nEnd the Squareverse simulation (e)\n\nOption: ")
        assert user_selection in valid_options, "E: that was not a valid option!"

        if user_selection == "s":
            
            number_of_squares = input("Enter the number of Squares to spawn (m = max allowed, h = half max, q = quarter max): ")

            if number_of_squares == "m":
                number_of_squares = (squareverse.max_number_of_squares - len(squareverse.created_squares))
            elif number_of_squares == "h":
                number_of_squares = squareverse.max_number_of_squares // 2
            elif number_of_squares == "q":
                number_of_squares = squareverse.max_number_of_squares // 4
            # else:
            #     number_of_squares = int(number_of_squares)

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
            
            squareverse.moveSquares()

        else:
            squareverse.destroy_squareverse()
            break





class Square():

    
    def __init__(self, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y, window):
        
        self.window = window
        self.top_left_corner_x = top_left_corner_x
        self.top_left_corner_y = top_left_corner_y
        self.bottom_right_corner_x = bottom_right_corner_x
        self.bottom_right_corner_y = bottom_right_corner_y
        self.square_color = color_rgb(0, randrange(0, 256), randrange(0, 256)) #testing random Square color
        self.square_id = 0
        

        self.drawSquare()



    def drawSquare(self):

        self.square = Rectangle(Point(self.top_left_corner_x, self.top_left_corner_y), Point(self.bottom_right_corner_x, self.bottom_right_corner_y))
        
        self.coordinates = self.square.getCenter()

        self.square.setFill(self.square_color)
        
        self.square.draw(self.window)



    def moveSquare(self, squareverse):
        
        # ***to-do***
        # add logic to increase color of Square for each consecutive collision
        # split method for collision/border check into separate methods


        squareverse_size = squareverse.squareverse_size
        squareverse_grid_spacing = squareverse.squareverse_grid_spacing
        list_of_squares = squareverse.created_squares
        movement_dx = 0
        movement_dy = 0
        list_of_coordinates = []
        collision_detected = True
        number_of_collisions = 0
        directions_already_tried = set()
        direction_last_moved = ""
        direction_opposites = {"up": "down", "down": "up", "left": "right", "right": "left"}
        self.possible_directions = squareverse.directions


        # UPDATED MOVING LOGIC
        
        # reset Square color
        self.square.setFill(self.square_color)
        
        if direction_last_moved == "":
            
            # randomly picks a directions to move in
            chosen_direction = choice(tuple(possible_directions))
            
            print(f"\n\nSquare [{self.square_id}] will attempt to move [{chosen_direction.upper()}]") #D
            print(f"\n\nCoordinates for Square [{self.square_id}] before moving are [X: {self.coordinates.getX()} Y: {self.coordinates.getY()}]") #D

            # # checks if direction has already been tried
            # while chosen_direction in directions_already_tried:

            #     print(f"\n\nAlready tried direction [{chosen_direction.upper()}] so choosing another direction") #D
            #     chosen_direction = choice(tuple(possible_directions))
            
            # else:

            #     pass
            

            # directions_already_tried.add(chosen_direction)

            # print(f"\n\nDirections tried for Square [{self.square_id}] are [{directions_already_tried}]") #D

            collision = collisionCheck(squareverse, chosen_direction)

             






            self.square.move(possible_directions(chosen_direction[0]), possible_directions(chosen_direction[1]))

            # gets updated coordinates for Square
            self.coordinates = self.square.getCenter()
            
            print(f"\n\nUpdated coordinates for Square {self.square_id} after moving are [X: {self.coordinates.getX()} Y: {self.coordinates.getY()}]") #D

            # checks for collisions with Squareverse border
            collision_detected = False

            print("\n\nRunning logic for border detection!") #D
            
            if self.coordinates.getX() <= squareverse_grid_spacing or self.coordinates.getY() <= squareverse_grid_spacing or self.coordinates.getX() >= (squareverse_size + squareverse_grid_spacing) or self.coordinates.getY() >= (squareverse_size + squareverse_grid_spacing):
                
                collision_detected = True
                self.square.setFill("Yellow")
                self.square.move((movement_dx * -1), (movement_dy * -1)) # reverses Square movement
                self.coordinates = self.square.getCenter()
                number_of_collisions += 1

                
                print("\n\nCollision with Squareverse border detected!") # debug

                # break

            else:


            
        
        
        # else:
        #     tdb














        # # print("\n\nLength of array 'list_of_squares': " + str(len(list_of_squares))) # debug
        # if len(list_of_squares) > 1:

        #     if direction_last_moved == "":
                
        #         while collision_detected == True and number_of_collisions < 4:

        #             # reset Square color
        #             self.square.setFill(self.square_color)
                    
        #             # randomly pick a direction for Square move in
        #             possible_directions = {"up", "down", "left", "right"}
        #             chosen_direction = choice(tuple(possible_directions))
        #             print(f"\n\n{chosen_direction} has been chosen for movement direction") #D

        #             print(f"\n\nCoordinates for Square [{self.square_id}] before moving are [{self.coordinates}]") #D
        #             print(f"Square [{self.square_id}] will attempt to move [{chosen_direction}]") #D

        #             # check if direction has already been tried
        #             while direction in directions_already_tried:
                        
        #                 print(f"\n\nAlready tried direction [{chosen_direction}] so choosing another direction") #D
        #                 chosen_direction = choice(tuple(possible_directions))
                    
        #             directions_already_tried.add(chosen_direction)
        #             print(f"\n\nDirections tried for Square [{self.square_id}] are [{directions_already_tried}]") #D
                
        #             if direction == "up":
                    
        #                 movement_dx = 0
        #                 movement_dy = -squareverse_grid_spacing

        #             elif direction == "down":

        #                 movement_dx = 0
        #                 movement_dy = squareverse_grid_spacing

        #             elif direction == "left":

        #                 movement_dx = -squareverse_grid_spacing
        #                 movement_dy = 0

        #             elif direction == "right":
                    
        #                 movement_dx = squareverse_grid_spacing
        #                 movement_dy = 0

        #             # move Square one grid space in randomly chosen direction
        #             self.square.move(movement_dx, movement_dy)
                    
                    # # gets updated coordinates for Square
                    # self.coordinates = self.square.getCenter()
                    # print(f"\n\nUpdated coordinates for Square {self.square_id}: " + str(self.coordinates)) # debug
                    # print(f"Updated X coordinates for Square {self.square_id}: " + str(self.coordinates.getX())) # debug
                    # print(f"Updated Y coordinates for Square {self.square_id}: " + str(self.coordinates.getY())) # debug
                    # # print(type(self.coordinates)) # debug

        #             # checks for collisions with Squareverse border and other Squares
        #             collision_detected = False
                    
                    # print("\n\nRunning logic for border detection!") #D
                    # if self.coordinates.getX() <= squareverse_grid_spacing or self.coordinates.getY() <= squareverse_grid_spacing or self.coordinates.getX() >= (squareverse_size + squareverse_grid_spacing) or self.coordinates.getY() >= (squareverse_size + squareverse_grid_spacing):
                        
                    #     collision_detected = True
                    #     self.square.setFill("Yellow")
                    #     self.square.move((movement_dx * -1), (movement_dy * -1)) # reverses Square movement
                    #     self.coordinates = self.square.getCenter()
                    #     number_of_collisions += 1

                        
                    #     print("\n\nCollision with Squareverse border detected!") # debug

                    #     # break

                    # else:

        #                 print("\n\nRunning logic for collision detection!") # debug
        #                 for coordinates in list_of_coordinates:
                            
        #                     coordinate_x = coordinates.getX()
        #                     coordinate_y = coordinates.getY()

        #                     if coordinate_x == self.coordinates.getX() and coordinate_y == self.coordinates.getY():
                                
        #                         collision_detected = True
        #                         self.square.setFill("Red")
        #                         self.square.move((movement_dx * -1), (movement_dy * -1)) # reverses Square movement
        #                         self.coordinates = self.square.getCenter()
        #                         number_of_collisions += 1
        #                         print(f"\n\nCollision with another Square detected!")

        #                         break
                        
        #     print(f"\n\nNumber of collisions for Square {self.square_id} is: {number_of_collisions}")
        #     print(f"Square {self.square_id} has moved {direction.upper()}!") # debug
        #     print(f"Current coordinates for Square {self.square_id} is: {self.coordinates}") # debug

        #     # builds the list of Square center point coordinates (Point objects) for all Squares that currently exist (including this Square)
        #     for square in list_of_squares:
        #         coordinates = square.coordinates
        #         list_of_coordinates.append(coordinates)
        #     # print("\n\nList of Square coordinates: " + str(list_of_coordinates)) # debug

        #     while collision_detected == True and number_of_collisions < 4:

        #         # reset Square color
        #         self.square.setFill(self.square_color)
                
        #         # randomly pick a direction for Square move in
        #         direction = choice(["up", "down", "left", "right"])
        #         print(f"\n\nCoordinates for Square [{self.square_id}] before moving are [{self.coordinates}]") #D
        #         print(f"Square [{self.square_id}] will attempt to move [{direction.upper()}]") #D

        #         # check if direction has already been tried
        #         while direction in directions_already_tried:
                    
        #             print(f"\n\nAlready tried direction [{direction.upper()}] so choosing another direction") #D
        #             direction = choice(["up", "down", "left", "right"])
                
        #         directions_already_tried.add(direction)
        #         print(f"\n\nDirections tried for Square [{self.square_id}] are [{directions_already_tried}]") #D
            
        #         if direction == "up":
                
        #             movement_dx = 0
        #             movement_dy = -squareverse_grid_spacing

        #         elif direction == "down":

        #             movement_dx = 0
        #             movement_dy = squareverse_grid_spacing

        #         elif direction == "left":

        #             movement_dx = -squareverse_grid_spacing
        #             movement_dy = 0

        #         elif direction == "right":
                
        #             movement_dx = squareverse_grid_spacing
        #             movement_dy = 0

        #         # move Square one grid space in randomly chosen direction
        #         self.square.move(movement_dx, movement_dy)
                
        #         # gets updated coordinates for Square
        #         self.coordinates = self.square.getCenter()
        #         print(f"\n\nUpdated coordinates for Square {self.square_id}: " + str(self.coordinates)) # debug
        #         print(f"Updated X coordinates for Square {self.square_id}: " + str(self.coordinates.getX())) # debug
        #         print(f"Updated Y coordinates for Square {self.square_id}: " + str(self.coordinates.getY())) # debug
        #         # print(type(self.coordinates)) # debug

        #         # checks for collisions with Squareverse border and other Squares
        #         collision_detected = False
                
        #         print("\n\nRunning logic for border detection!") #D
        #         if self.coordinates.getX() <= squareverse_grid_spacing or self.coordinates.getY() <= squareverse_grid_spacing or self.coordinates.getX() >= (squareverse_size + squareverse_grid_spacing) or self.coordinates.getY() >= (squareverse_size + squareverse_grid_spacing):
                    
        #             collision_detected = True
        #             self.square.setFill("Yellow")
        #             self.square.move((movement_dx * -1), (movement_dy * -1)) # reverses Square movement
        #             self.coordinates = self.square.getCenter()
        #             number_of_collisions += 1
                    
        #             print("\n\nCollision with Squareverse border detected!") # debug

        #             # break

        #         else:

        #             print("\n\nRunning logic for collision detection!") # debug
        #             for coordinates in list_of_coordinates:
                        
        #                 coordinate_x = coordinates.getX()
        #                 coordinate_y = coordinates.getY()

        #                 if coordinate_x == self.coordinates.getX() and coordinate_y == self.coordinates.getY():
                            
        #                     collision_detected = True
        #                     self.square.setFill("Red")
        #                     self.square.move((movement_dx * -1), (movement_dy * -1)) # reverses Square movement
        #                     self.coordinates = self.square.getCenter()
        #                     number_of_collisions += 1
        #                     print(f"\n\nCollision with another Square detected!")

        #                     break
                        
        #     print(f"\n\nNumber of collisions for Square {self.square_id} is: {number_of_collisions}")
        #     print(f"Square {self.square_id} has moved {direction.upper()}!") # debug
        #     print(f"Current coordinates for Square {self.square_id} is: {self.coordinates}") # debug
      
        # else:
   
        #     print("\n\nNo other Squares detected!") # debug
        #     while collision_detected == True:

        #         direction = choice(["up", "down", "left", "right"])
            
        #         # checks if direction has already been tried
        #         while direction in directions_already_tried:
                    
        #             print(f"\n\nAlready tried direction {direction.upper()}! Choosing another direction!") # debug
        #             direction = choice(["up", "down", "left", "right"])
                
        #         directions_already_tried.add(direction)
        #         print(f"\n\nDirections tried: {directions_already_tried}") # debug

        #         if direction == "up":
                
        #             movement_dx = 0
        #             movement_dy = (squareverse_grid_spacing * 1)

        #         elif direction == "down":

        #             movement_dx = 0
        #             movement_dy = squareverse_grid_spacing * - 1

        #         elif direction == "left":

        #             movement_dx = (squareverse_grid_spacing * - 1)
        #             movement_dy = 0

        #         elif direction == "right":
                
        #             movement_dx = squareverse_grid_spacing
        #             movement_dy = 0

        #         # attempts to move Square one grid space in randomly chosen direction
        #         self.square.move(movement_dx, movement_dy)
                
        #         # gets updated coordinates for Square
        #         self.coordinates = self.square.getCenter()
            
        #         # checks for collisions with Squareverse boarder
        #         collision_detected = False
                
        #         print("\n\nRunning logic for border detection!") # debug
        #         if self.coordinates.getX() <= 0 or self.coordinates.getY() <= 0 or self.coordinates.getX() >= 800 or self.coordinates.getY() >= 800:
                    
        #             collision_detected = True
        #             self.square.setFill("Yellow")
        #             self.square.move((movement_dx * -1), (movement_dy * -1)) # reverses Square movement
        #             self.coordinates = self.square.getCenter()
                    
        #             print("\n\nCollision with Squareverse boarder detected!") # debug
            
            
        #     print(f"\n\nSquare {self.square_id} has moved {direction.upper()}!") # debug
        #     print(f"Current coordinates for Square {self.square_id} is: {self.coordinates}") # debug



    def collisionCheck(self, squareverse, chosen_direction):

        # creates an  clone of the Square ("Square's soul")
        square_soul = self.square.clone()
        
        # moves Square's soul to check for collisions
        square_soul.move(self.possible_directions(chosen_direction[0]), self.possible_directions(chosen_direction[1]))

        # checks where Square's soul currently is
        coordinates = square_soul.getCenter()

        print(f"\n\nCoordinates of the soul for Square [{self.square_id}] are [X: {square_soul.getX()} Y: {square_soul.getY()}]")

        print("\n\nRunning logic for border detection!") #D

        if coordinates.getX() <= squareverse_grid_spacing or coordinates.getY() <= squareverse_grid_spacing or coordinates.getX() >= (squareverse_size + squareverse_grid_spacing) or coordinates.getY() >= (squareverse_size + squareverse_grid_spacing):

            collision_detected = True
            square_soul.delItem()

            print("\n\nCollision with Squareverse border detected") #D

            return collision_detected
   







    # def moveSquare(square, x1y1):
    # square.move(x1y1 * 7, x1y1 * 7)

    # coordinates = square.world()

    # print(coordinates)




# -- to-do --
# figure out why collision logic isn't working
# figure out why squares aren't being spawned into every available grid
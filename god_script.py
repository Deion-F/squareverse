from time import sleep
from graphics import GraphWin, Point, Line, Rectangle, color_rgb
from random import randint, randrange, choice
# import threading
# end of imports

#COMMENT LEGEND
# Code for debugging - #D
# Code for providing information - #I


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
        
        print(f"\n\n***Squareverse Values***\nSquareverse ID: [{self.squareverse_id}]\nSquareverse Name: [{self.squareverse_name}]\nSquareverse Size: [{self.squareverse_size}px]\nSquareverse Grid Spacing: [{self.squareverse_grid_spacing}px]\nSquareverse Window Size: [{self.squareverse_window_size}px]") #D
        
        self.createSquareverseWindow()

    

    def createSquareverseWindow(self):
        
        # creates squareverse window, sets name & size
        self.window = GraphWin(title = self.squareverse_name, width = self.squareverse_window_size, height = self.squareverse_window_size)
        
        # sets background color of squareverse using RGB
        self.window.setBackground(self.squareverse_window_background_color)

        print(f"\n\nSquareverse window for has been successfully created for [{self.squareverse_name}]") #I
        
        # generates grid for squareverse
        self.createSquareverseGrid()



    def createSquareverseGrid(self):
        
        print(f"\n\nCreating Squareverse grid for [{self.squareverse_name}] using grid spacing of [{self.squareverse_grid_spacing}px]") #I

        vertical_starting_point = self.squareverse_grid_spacing
        horizontal_starting_point = self.squareverse_grid_spacing
        number_of_lines = (self.squareverse_size // self.squareverse_grid_spacing) + 1 # probably needs tuning to create the exact amount of lines required
        print(f"\n\n[{number_of_lines}] grid lines required") #D

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



    def createSquares(self, number_of_squares = 1):

        # creates number of Squares provided by number_of_squares
        for _ in range(number_of_squares):
            
            grid_occupied = True
            squareverse_max_xy = self.squareverse_size

            if len(self.created_squares) > 0:
               
                while grid_occupied == True:
               
                    top_left_corner_x = randrange(0, squareverse_max_xy, self.squareverse_grid_spacing)
                    top_left_corner_y = randrange(0, squareverse_max_xy, self.squareverse_grid_spacing)

                    for square in self.created_squares:
                        
                        if square.top_left_corner_x == top_left_corner_x and square.top_left_corner_y == top_left_corner_y:
                            
                            # print("A Square already exists in this location!") # debug
                            grid_occupied = True
                            
                            break

                        else:
                            
                            grid_occupied = False
            
            else:
                
                top_left_corner_x = randrange(0, squareverse_max_xy, self.squareverse_grid_spacing)
                top_left_corner_y = randrange(0, squareverse_max_xy, self.squareverse_grid_spacing)

            bottom_right_corner_x = top_left_corner_x + self.squareverse_grid_spacing
            bottom_right_corner_y = top_left_corner_y + self.squareverse_grid_spacing

            square = Square(760, 0, 800, 40, self.window) #T

            # adds Square object to array for Squareverse
            self.created_squares.append(square)

            # defines the Square ID based on the array index            
            (self.created_squares[len(self.created_squares) - 1]).square_id = len(self.created_squares) - 1


            print(f"\n\nSquare {(self.created_squares[len(self.created_squares) - 1]).square_id} has been spawned at - top:{(self.created_squares[len(self.created_squares) - 1]).top_left_corner_x}:{(self.created_squares[len(self.created_squares) - 1]).top_left_corner_y} bottom:{(self.created_squares[len(self.created_squares) - 1]).bottom_right_corner_x}:{(self.created_squares[len(self.created_squares) - 1]).bottom_right_corner_y} center: {(self.created_squares[len(self.created_squares) - 1]).coordinates}") # debug



    def moveSquares(self, duration):


        mouse_clicked = self.window.checkMouse()

        # for _ in range(duration):

        # stops the simulation on the next cycle after the mouse is clicked
        while mouse_clicked == None:
        # print(f"\n\nMouse clicked = {mouse_clicked}")
            
            mouse_clicked = self.window.checkMouse()
            for square in self.created_squares:

                print(f"\n\nMouse clicked = {mouse_clicked}") # debug
                square.moveSquare(self)

            # controls the movement delay between all Squares
            sleep(0.5)



    # closes the Squareverse window
    def destroy_squareverse(self):
        
        self.window.close()
        print(f"Ending the Squareverse simulation for {self.squareverse_name}!")



# ---CLASSLESS FUNCTIONS--- 



def createSquareverse():
    
    squareverse_id = randint(1, 100)
    squareverse_name = "Squareverse" + str(squareverse_id)
    squareverse_size = input("\n\nSquareverse Size (default - 800px): ")

    assert len(squareverse_size) == 0 or squareverse_size.isnumeric == True, "E: the value entered was not a number!"

    if len(squareverse_size) == 0:
        squareverse_size = 800

    squareverse_grid_spacing = input("Grid Spacing (default - random): ")

    assert len(squareverse_grid_spacing) == 0 or squareverse_grid_spacing.isnumeric == True, "E: the value entered was not a number!"

    if len(squareverse_grid_spacing) == 0:
        squareverse_grid_spacing = 40
        # squareverse_grid_spacing = randrange(20, 80, 20)

    # creates Squareverse using provided values
    squareverse = Squareverse(squareverse_id, squareverse_name, int(squareverse_size), int(squareverse_grid_spacing))
    print(f"\n\nThe new Squareverse, {squareverse.squareverse_name}, has been successfully created!")


    return squareverse
    




def showMenu(squareverse):

    valid_options = ["s", "d", "a", "m", "e"]

    while True:
       
        user_selection = input("\n\nPlease select what you want to do:\nSpawn a Square (s)\nDelete a Square (d)\nDelete all Squares (a)\nMove Squares (m)\nEnd the Squareverse simulation (e)\n\nOption: ")
        assert user_selection in valid_options, "E: that was not a valid option!"

        if user_selection == "s":
            
            numSquares = input("How many Squares would you like to spawn: ")
            squareverse.createSquares(int(numSquares))

        elif user_selection == "d":
            pass
        elif user_selection == "a":
            pass
        elif user_selection == "m":
            
            default_duration = 10
            duration = input(f"Enter a duration for movement (default {default_duration}): ")
            
            if duration == "" or duration.isnumeric == False:
                duration = default_duration

            print(f"Moving Squares for {duration} cycles. Please wait...")
            
            squareverse.moveSquares(int(duration))

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
        self.square_color = color_rgb(255, 255, 255)
        self.square_id = 0
        

        self.drawSquare()



    def drawSquare(self):
        # top_corner = Point(top_corner_dimension, top_corner_dimension + (self.squareverse_grid_spacing * 3))
        # bottom_corner = Point(bottom_corner_dimension, bottom_corner_dimension + (self.squareverse_grid_spacing * 3))

        self.square = Rectangle(Point(self.top_left_corner_x, self.top_left_corner_y), Point(self.bottom_right_corner_x, self.bottom_right_corner_y))
        
        self.coordinates = self.square.getCenter()

        self.square.setFill(self.square_color)
        
        self.square.draw(self.window)



    def moveSquare(self, squareverse):
        
        # ***to-do***
        # add logic in collision check to avoid edges of Squareverse
        # add logic to increase color of Square for each consecutive collision
        # split method for collision/border check into separate methods


        squareverse_size = squareverse.squareverse_size
        list_of_squares = squareverse.created_squares
        squareverse_grid_spacing = squareverse.squareverse_grid_spacing
        movement_dx = 0
        movement_dy = 0
        list_of_coordinates = []
        collision_detected = True
        number_of_collisions = 0
        directions_already_tried = set()

        # print("\n\nLength of array 'list_of_squares': " + str(len(list_of_squares))) # debug
        if len(list_of_squares) > 1:

            # builds the list of Square center point coordinates (Point objects) for all Squares that currently exist (including this Square)
            for square in list_of_squares:
                coordinates = square.coordinates
                list_of_coordinates.append(coordinates)
            # print("\n\nList of Square coordinates: " + str(list_of_coordinates)) # debug

            while collision_detected == True and number_of_collisions < 4:

                # reset Square color to white
                self.square.setFill(color_rgb(255, 255, 255))
                
                # randomly pick a direction for Square move in
                direction = choice(["up", "down", "left", "right"])
                print(f"\n\nCoordinates for Square {self.square_id} before moving is {self.coordinates}") # debug
                print(f"Square {self.square_id} will attempt to move {direction.upper()}") # debug

                # check if direction has already been tried
                while direction in directions_already_tried:
                    
                    print(f"\n\nAlready tried direction {direction.upper()}! Choosing another direction!") # debug
                    direction = choice(["up", "down", "left", "right"])
                
                directions_already_tried.add(direction)
                print(f"\n\nDirections tried for Square {self.square_id}: {directions_already_tried}") # debug
            
                if direction == "up":
                
                    movement_dx = 0
                    movement_dy = 40

                elif direction == "down":

                    movement_dx = 0
                    movement_dy = -40

                elif direction == "left":

                    movement_dx = -40
                    movement_dy = 0

                elif direction == "right":
                
                    movement_dx = 40
                    movement_dy = 0

                # move Square one grid space in randomly chosen direction
                self.square.move(movement_dx, movement_dy)
                
                # gets updated coordinates for Square
                self.coordinates = self.square.getCenter()
                print(f"\n\nUpdated coordinates for Square {self.square_id}: " + str(self.coordinates)) # debug
                print(f"Updated X coordinates for Square {self.square_id}: " + str(self.coordinates.getX())) # debug
                print(f"Updated Y coordinates for Square {self.square_id}: " + str(self.coordinates.getY())) # debug
                # print(type(self.coordinates)) # debug

                # checks for collisions with Squareverse border and other Squares
                collision_detected = False
                
                print("\n\nRunning logic for border detection!") # debug
                if self.coordinates.getX() <= 0 or self.coordinates.getY() <= 0 or self.coordinates.getX() >= 800 or self.coordinates.getY() >= 800:
                    
                    collision_detected = True
                    self.square.setFill("Yellow")
                    self.square.move((movement_dx * -1), (movement_dy * -1)) # reverses Square movement
                    self.coordinates = self.square.getCenter()
                    number_of_collisions += 1
                    
                    print("\n\nCollision with Squareverse border detected!") # debug

                else:

                    print("\n\nRunning logic for collision detection!") # debug
                    for coordinates in list_of_coordinates:
                        
                        coordinate_x = coordinates.getX()
                        coordinate_y = coordinates.getY()

                        if coordinate_x == self.coordinates.getX() and coordinate_y == self.coordinates.getY():
                            
                            collision_detected = True
                            self.square.setFill("Red")
                            self.square.move((movement_dx * -1), (movement_dy * 1)) # reverses Square movement
                            self.coordinates = self.square.getCenter()
                            number_of_collisions += 1
                            print(f"\n\nCollision with another Square detected!")

                            break
                        
            print(f"\n\nNumber of collisions for Square {self.square_id} is: {number_of_collisions}")
            print(f"Square {self.square_id} has moved {direction.upper()}!") # debug
            print(f"Current coordinates for Square {self.square_id} is: {self.coordinates}") # debug
      
        else:
   
            print("\n\nNo other Squares detected!") # debug
            while collision_detected == True:

                direction = choice(["up", "down", "left", "right"])
            
                # checks if direction has already been tried
                while direction in directions_already_tried:
                    
                    print(f"\n\nAlready tried direction {direction.upper()}! Choosing another direction!") # debug
                    direction = choice(["up", "down", "left", "right"])
                
                directions_already_tried.add(direction)
                print(f"\n\nDirections tried: {directions_already_tried}") # debug

                if direction == "up":
                
                    movement_dx = 0
                    movement_dy = (squareverse_grid_spacing * 1)

                elif direction == "down":

                    movement_dx = 0
                    movement_dy = squareverse_grid_spacing * - 1

                elif direction == "left":

                    movement_dx = (squareverse_grid_spacing * - 1)
                    movement_dy = 0

                elif direction == "right":
                
                    movement_dx = squareverse_grid_spacing
                    movement_dy = 0

                # attempts to move Square one grid space in randomly chosen direction
                self.square.move(movement_dx, movement_dy)
                
                # gets updated coordinates for Square
                self.coordinates = self.square.getCenter()
            
                # checks for collisions with Squareverse boarder
                collision_detected = False
                
                print("\n\nRunning logic for border detection!") # debug
                if self.coordinates.getX() <= 0 or self.coordinates.getY() <= 0 or self.coordinates.getX() >= 800 or self.coordinates.getY() >= 800:
                    
                    collision_detected = True
                    self.square.setFill("Yellow")
                    self.square.move((movement_dx * -1), (movement_dy * -1)) # reverses Square movement
                    self.coordinates = self.square.getCenter()
                    
                    print("\n\nCollision with Squareverse boarder detected!") # debug
            
            
            print(f"\n\nSquare {self.square_id} has moved {direction.upper()}!") # debug
            print(f"Current coordinates for Square {self.square_id} is: {self.coordinates}") # debug



    # def collisionCheck():


   








    # def moveSquare(square, x1y1):
    # square.move(x1y1 * 7, x1y1 * 7)

    # coordinates = square.world()

    # print(coordinates)




# -- to-do --
# figure out why collision logic isn't working
# figure out why squares aren't being spawned into every available grid
#!/usr/bin/env python3.7
from random import choice, randint
# from mongo import Mongo
from god_script import Squareverse

# end of imports

def createSquareverseSimulation():

    squareverse_id = randint(0, 100)
    squareverse_name = f"Squareverse #{squareverse_id}"
    squareverse_default_window_size = 3
    squareverse_default_grid_size = 25
    invalid_squareverse_size = True


    while invalid_squareverse_size == True:

        squareverse_size = input("\n\nSelect Squareverse size (1 - 10): ") # INPUT
        
        if len(squareverse_size) == 0:

            squareverse_size = squareverse_default_window_size
            invalid_squareverse_size = False

        elif float(squareverse_size) % 1 != 0:

            print("\n\nPlease choose a whole number for Squareverse size") # INFO

        elif int(squareverse_size) <= 10 and int(squareverse_size) >= 1:
        
            invalid_squareverse_size = False

        else:

            print("\n\nPlease choose a valid size for Squareverse") # INFO

    squareverse_size_px = (int(squareverse_size) * 100) # calculates Squareverse window size in px
    valid_grid_sizes = [i for i in range(10, ((squareverse_size_px // 10) + 1)) if squareverse_size_px % i == 0 and (squareverse_size_px / i) % 2 == 0]
    
    print(f"\n\nList of valid grid sizes are [{valid_grid_sizes}]") # INFO
    
    squareverse_grid_spacing = input("\n\nSelect a Squareverse grid size: ") # INPUT
    
    if squareverse_size == squareverse_default_window_size and len(squareverse_grid_spacing) == 0:

        squareverse_grid_spacing = squareverse_default_grid_size
    
    elif len(squareverse_grid_spacing) == 0:

        squareverse_grid_spacing = choice(valid_grid_sizes)
    
    else:

        squareverse_grid_spacing = int(squareverse_grid_spacing)
      
    
    squareverse = Squareverse(squareverse_id, squareverse_name)
    
    squareverse.createSquareverseWindow(squareverse_size_px, squareverse_grid_spacing)
    
    # print(f"\n\nList of valid grid sizes are [{valid_grid_sizes}]") # debug
    # print(f"\n\nSelected grid spacing is [{squareverse_grid_spacing}]") # debug
    print(f"\n\n{squareverse.squareverse_name} has been successfully created") # DEBUG


    return squareverse





def main():
    
    # squareverse = Squareverse()
    squareverse = createSquareverseSimulation()

    squareverse.showSquareverseMenu()



if __name__ == "__main__":
    
    main()
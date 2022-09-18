#!/usr/bin/env python3.7
from random import choice, randint
# from mongo import Mongo
from god_script import Squareverse

# end of imports

def createSquareverseSimulation():


    squareverse_id = randint(0, 100)
    squareverse_name = f"Squareverse {squareverse_id}"
    squareverse_default_size = 5
    invalid_squareverse_size = True


    while invalid_squareverse_size == True:

        squareverse_size = input("\n\nSelect size for Squareverse (1 - 10): ") #info
        
        if len(squareverse_size) == 0:

            squareverse_size = squareverse_default_size
            invalid_squareverse_size = False

        elif float(squareverse_size) % 1 != 0:

            print("\n\nPlease choose a whole number for Squareverse size") #info

        elif int(squareverse_size) <= 10 and int(squareverse_size) >= 1:
        
            invalid_squareverse_size = False

        else:

            print("\n\nPlease choose a valid size for Squareverse") #info

    squareverse_size = (int(squareverse_size) * 100) #calculates Squareverse window size in px
    valid_grid_sizes = [i for i in range(10, ((squareverse_size // 10) + 1)) if squareverse_size % i == 0 and (squareverse_size / i) % 2 == 0]
    # print(f"\n\nList of valid grid sizes are [{valid_grid_sizes}]") #debug
    squareverse_grid_spacing = choice(valid_grid_sizes)
    # print(f"\n\nSelected grid spacing is [{squareverse_grid_spacing}]") #debug
    squareverse = Squareverse(squareverse_id, squareverse_name)
    squareverse.createSquareverseWindow(squareverse_size, squareverse_grid_spacing)
    
    print(f"\n\n{squareverse.squareverse_name} has been successfully created") #debug


    return squareverse





def main():
    
    # squareverse = Squareverse()
    squareverse = createSquareverseSimulation()

    squareverse.showSquareverseMenu()



if __name__ == "__main__":
    
    main()
#!/usr/bin/env python3.7
from pymongo import MongoClient
import pprint



class Mongo:

    def __init__(self):
        
        self.client = MongoClient('localhost', 27017)
        self.db = self.client.squareverse


    def insert_valid_directions(self, grid_spacing):

        dbCollection = self.db.valid_directions
        valid_directions = [
            {
            "direction": "up",
            "x": 0, 
            "y": (grid_spacing * - 1), 
            "inverse": "down"
            },
            {"direction": "down",
            "x": 0, 
            "y": grid_spacing, 
            "inverse": "up"
            }, 
            {"direction": "left",
            "x": (grid_spacing * - 1), 
            "y": 0,
            "inverse": "right"
            },
            {"direction": "right",
            "x": grid_spacing, 
            "y": 0,
            "inverse": "left"}
        ]

        results = dbCollection.insert_many(valid_directions)
        # print(results.inserted_ids)


    def delete_valid_directions(self):

        dbCollection = self.db.valid_directions
        dbCollection.delete_many({})
        self.db.square_coordinates.delete_many({})
        self.db.valid_top_left_corner_xy.delete_many({})


    def insert_square_coordinates(self, square, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):

        dbCollection = self.db.square_coordinates
        square_coordinates = [
            {
            #"square_object": square,
            "square_id": square.square_id,
            "top_left_corner_x": top_left_corner_x,
            "top_left_corner_y": top_left_corner_y,
            "bottom_right_corner_x": bottom_right_corner_x,
            "bottom_right_corner_y": bottom_right_corner_y
            }
        ]

        results = dbCollection.insert_many(square_coordinates)


    def create_valid_top_left_corner_xy(self, squareverse_grid_spacing, number_of_lines):

        dbCollection = self.db.valid_top_left_corner_xy

        starting_x = squareverse_grid_spacing
        starting_y = squareverse_grid_spacing

        for _ in range(number_of_lines - 1):

            for _ in range(number_of_lines -1):

                top_left_corner_xy = {
                
                    "top_left_corner_x": starting_x,
                    "top_left_corner_y": starting_y,
                    "bottom_right_corner_x": starting_x + squareverse_grid_spacing,
                    "bottom_right_corner_y": starting_y + squareverse_grid_spacing,
                    "occupied": False,
                    "previous_direction": None
                    }

                results = dbCollection.insert_one(top_left_corner_xy)

                
                starting_y = starting_y + squareverse_grid_spacing

            starting_x = starting_x + squareverse_grid_spacing
            starting_y = squareverse_grid_spacing

    
    def get_available_coordinates(self, number_of_squares):

        dbCollection = self.db.valid_top_left_corner_xy
        free_space = True

        totals = dbCollection.aggregate([{ "$match": { "occupied": False }}, { "$sample": { "size": number_of_squares }}, { "$count": "total"}]) # gets total number of matching documents
        # .find({"occupied": "false"})
        #.limit(number_of_squares)
        # results = list(dbCollection.find({"occupied": "false"}).limit(number_of_squares))
        # result_list = list(results)
        
        # pprint.pprint(totals[0])
        
        try:

            if totals.next()["total"] != 0:
                
                results = dbCollection.aggregate([{ "$match": { "occupied": False }}, { "$sample": { "size": number_of_squares } }])

                return free_space, results
            
            else:
            
                free_space = False
                
                print("No results found!")
                return free_space, results
                

        except:

            print("No next cursor")



    # def get_available_coordinates_testing(self):

    #     dbCollection = self.db.valid_top_left_corner_xy
    #     free_space = True

    #     totals = dbCollection.aggregate([{ "$match": { "occupied": False }}, { "$sample": { "size": 5 }}, { "$count": "total"}])
        
    #     try:

    #      pprint.pprint(totals.next()["total"])

    #     except:

    #         print("No next cursor")




        # .find({"occupied": "false"})
        #.limit(number_of_squares)
        # results = list(dbCollection.find({"occupied": "false"}).limit(number_of_squares))
        # result_list = list(results)
        
        # pprint.pprint(results.total)

        # for result in results:
                
        #     pprint.pprint(result["total"])
        
        # list_length = len(list(results))
        
        # if list_length != 0:

        #     results = dbCollection.aggregate([{ "$match": { "occupied": "false" }}, { "$sample": { "size": 5 } }])

        #     for result in results:
                
        #         pprint.pprint(result["_id"])

        #     return free_space, results
        
        # else:
            
        #     free_space = False
            
        #     return free_space, results
        #     print("No results found!")



    def update_mongodb(self, mongo_query, updated_value):

        dbCollection = self.db.valid_top_left_corner_xy

        dbCollection.update_one(mongo_query, updated_value)



    def collision_check(self, square, squareverse, selected_direction):

        dbCollection = self.db.valid_top_left_corner_xy
        collision_detected = False
        top_left_corner_x_after_moving = square.top_left_corner_x + squareverse.valid_directions[selected_direction]['x']
        top_left_corner_y_after_moving = square.top_left_corner_y + squareverse.valid_directions[selected_direction]['y']
        results = dbCollection.aggregate([
            { 
                "$match": {
                    "$and":[
                        { "top_left_corner_x": top_left_corner_x_after_moving },
                        { "top_left_corner_y": top_left_corner_y_after_moving },
                        { "occupied": False }
                    ]
                }
            },
            { 
                "$count": "total"
            }
        ])

        # for result in results:

        #     pprint.pprint(result)
        # results = dbCollection.find_one({ "top_left_corner_x": top_left_corner_x_after_moving }, { "top_left_corner_y": top_left_corner_y_after_moving }, { "occupied": True })
        # more_results = results.next()["total"]
        # pprint.pprint(results)

        # logic for detecting Squareverse borders
        if top_left_corner_x_after_moving < squareverse.squareverse_grid_spacing or top_left_corner_y_after_moving < squareverse.squareverse_grid_spacing or top_left_corner_x_after_moving > (squareverse.squareverse_size + squareverse.squareverse_grid_spacing) or top_left_corner_y_after_moving > (squareverse.squareverse_size + squareverse.squareverse_grid_spacing):

            square.number_of_collisions = self.number_of_collisions + 1
            collision_detected = True
        
        elif results != 0:
        
            square.number_of_collisions = self.number_of_collisions + 1
            collision_detected = True


        return collision_detected



    def collision_check_testing(self, square, squareverse, selected_direction):

        dbCollection = self.db.valid_top_left_corner_xy
        collision_detected = False
        top_left_corner_x_after_moving = square.top_left_corner_x + squareverse.valid_directions[selected_direction]['x']
        top_left_corner_y_after_moving = square.top_left_corner_y + squareverse.valid_directions[selected_direction]['y']
        results = dbCollection.find_one({ "top_left_corner_x": top_left_corner_x_after_moving }, { "top_left_corner_y": top_left_corner_y_after_moving }, { "occupied": True })
        print(results)

        # logic for detecting Squareverse borders
        if top_left_corner_x_after_moving < squareverse.squareverse_grid_spacing or top_left_corner_y_after_moving < squareverse.squareverse_grid_spacing or top_left_corner_x_after_moving > (squareverse.squareverse_size + squareverse.squareverse_grid_spacing) or top_left_corner_y_after_moving > (squareverse.squareverse_size + squareverse.squareverse_grid_spacing):

            collision_detected = True
        
        elif len(results) != 0:
        
            collision_detected = True

        return collision_detected


            

        


        








# mongo = Mongo()




# mongo.create_valid_top_left_corner_xy(10, 31)
# mongo.get_available_coordinates_testing()

# mongo.insert_valid_directions(5)

# mongo.delete_valid_directions()
# mongo.db.valid_directions.drop_many({})
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

        for _ in range(number_of_lines):

            for _ in range(number_of_lines):

                top_left_corner_xy = {
                
                    "top_left_corner_x": starting_x,
                    "top_left_corner_y": starting_y,
                    "bottom_right_corner_x": starting_x + squareverse_grid_spacing,
                    "bottom_right_corner_y": starting_y + squareverse_grid_spacing,
                    "occupied": False
                    }

                results = dbCollection.insert_one(top_left_corner_xy)

                
                starting_y = starting_y + squareverse_grid_spacing

            starting_x = starting_x + squareverse_grid_spacing
            starting_y = squareverse_grid_spacing

    
    def get_available_coordinates(self, number_of_squares):

        dbCollection = self.db.valid_top_left_corner_xy
        free_space = True

        results = dbCollection.aggregate([{ "$match": { "occupied": False }}, { "$sample": { "size": number_of_squares } }])
        # .find({"occupied": "false"})
        #.limit(number_of_squares)
        # results = list(dbCollection.find({"occupied": "false"}).limit(number_of_squares))
        # result_list = list(results)
        list_length = len(list(results))
        
        if list_length != 0:

            results = dbCollection.aggregate([{ "$match": { "occupied": False }}, { "$sample": { "size": number_of_squares } }])

            
            
            # for result in results:
                
            #     print(result)

            return free_space, results
        
        else:
            
            free_space = False
            
            return free_space, results
            print("No results found!")



    def get_available_coordinates_testing(self):

        dbCollection = self.db.valid_top_left_corner_xy
        free_space = True

        results = dbCollection.aggregate([{ "$match": { "occupied": False }}, { "$sample": { "size": 5 }}])
        # .find({"occupied": "false"})
        #.limit(number_of_squares)
        # results = list(dbCollection.find({"occupied": "false"}).limit(number_of_squares))
        # result_list = list(results)
        
        # print(results)

        for result in results:
                
            pprint.pprint(result)
        
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
            

        


        








mongo = Mongo()




# mongo.create_valid_top_left_corner_xy(10, 31)
mongo.get_available_coordinates_testing()

# mongo.insert_valid_directions(5)

# mongo.delete_valid_directions()
# mongo.db.valid_directions.drop_many({})
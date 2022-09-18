#!/usr/bin/env python3.7
from pymongo import MongoClient



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







# mongo = Mongo()
# mongo.insert_valid_directions(5)

# mongo.delete_valid_directions()
# mongo.db.valid_directions.drop_many({})
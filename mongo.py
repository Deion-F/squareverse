#!/usr/bin/env python3.7
from pymongo import *
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


    def delete_squareverse_db(self):

        self.client.drop_database('squareverse')
        
        # dbCollection = self.db.valid_directions
        
        # self.db.valid_directions.delete_many({})
        # self.db.squareverse_coordinates.delete_many({})
        # self.db.squareverse_coordinates.delete_many({})


    def insert_squareverse_coordinates(self, square, top_left_corner_x, top_left_corner_y, bottom_right_corner_x, bottom_right_corner_y):

        dbCollection = self.db.squareverse_coordinates
        squareverse_coordinates = [
            {
            #"square_object": square,
            "square_id": square.square_id,
            "top_left_corner_x": top_left_corner_x,
            "top_left_corner_y": top_left_corner_y,
            "bottom_right_corner_x": bottom_right_corner_x,
            "bottom_right_corner_y": bottom_right_corner_y
            }
        ]

        results = dbCollection.insert_many(squareverse_coordinates)


    def create_parent_squareverse_coordinates(self, squareverse_grid_spacing, number_of_lines):

        dbCollection = self.db.squareverse_coordinates

        starting_x = squareverse_grid_spacing
        starting_y = squareverse_grid_spacing

        for _ in range(number_of_lines - 1):

            for _ in range(number_of_lines -1):

                square_coordinate = {
                
                    "top_left_corner_x": starting_x,
                    "top_left_corner_y": starting_y,
                    "bottom_right_corner_x": starting_x + squareverse_grid_spacing,
                    "bottom_right_corner_y": starting_y + squareverse_grid_spacing,
                    # "occupied": False,
                    "tkinter_id": None,
                    "previous_direction": None
                    }

                dbCollection.insert_one(square_coordinate)

                starting_y = starting_y + squareverse_grid_spacing

            starting_x = starting_x + squareverse_grid_spacing
            starting_y = squareverse_grid_spacing


    def create_child_squareverse_coordinates(self, child_squareverse_grid_spacing, child_squareverse_total_grid_lines, child_squareverse_child_square_ids, parent_square_tkinter_id):

        # dbString = f"self.db.squareverse_coordinates_{parent_square_id}"
        # dbCollection = self.db.squareverse_coordinates_+"{parent_square_id}"

        starting_x = child_squareverse_grid_spacing
        starting_y = child_squareverse_grid_spacing
        child_square_id = None
        next_child_square_id = 0
        mongo_bulk_insert_query = []

        for i in range(child_squareverse_total_grid_lines - 1):

            for i in range(child_squareverse_total_grid_lines -1):

                # mongo_query = { "_id": parent_square_id } # need to pass parent Square ID when calling function
                next_child_square_id = next_child_square_id + 1
                # child_square_id = next_child_square_id if next_child_square_id % 3 == 0 else None # controls how many child Squares are spawned
                child_square_id = next_child_square_id if next_child_square_id % 3 == 0 else None # TESTING
                
                child_squareverse_coordinate = {
                
                    "top_left_corner_x": starting_x,
                    "top_left_corner_y": starting_y,
                    "bottom_right_corner_x": starting_x + child_squareverse_grid_spacing,
                    "bottom_right_corner_y": starting_y + child_squareverse_grid_spacing,
                    "child_square_id": child_square_id,
                    "previous_direction": None
                    }

                mongo_query = InsertOne(child_squareverse_coordinate)
                mongo_bulk_insert_query.append(mongo_query)
                
                # self.db[f"squareverse_coordinates_{parent_square_tkinter_id}"].insert_one(child_squareverse_coordinate)
                
                if child_square_id != None:

                    child_squareverse_child_square_ids.append(child_square_id)
                
                
                
                # child_square_coordinate = {

                #     "$push": {

                #         "squareverse_child_coordinates": [{

                #             "top_left_corner_x": starting_x,
                #             "top_left_corner_y": starting_y,
                #             "bottom_right_corner_x": starting_x + squareverse_grid_spacing,
                #             "bottom_right_corner_y": starting_y + squareverse_grid_spacing,
                #             "occupied": False,
                #             "previous_direction": None
                #         }]
                #     }
                
                #     # "top_left_corner_x": starting_x,
                #     # "top_left_corner_y": starting_y,
                #     # "bottom_right_corner_x": starting_x + squareverse_grid_spacing,
                #     # "bottom_right_corner_y": starting_y + squareverse_grid_spacing,
                #     # "occupied": False,
                #     # "previous_direction": None
                # }

                # self.update_mongodb(mongo_query, child_square_coordinate)
                # dbCollection.insert_one(child_square_coordinate)

                
                starting_y = starting_y + child_squareverse_grid_spacing

            starting_x = starting_x + child_squareverse_grid_spacing
            starting_y = child_squareverse_grid_spacing

        
        self.db[f"squareverse_coordinates_{parent_square_tkinter_id}"].bulk_write(mongo_bulk_insert_query)
    
    
    def get_available_parent_squareverse_coordinates(self, number_of_squares):

        dbCollection = self.db.squareverse_coordinates
        free_space = True

        available_coordinates = dbCollection.aggregate([{ "$match": { "tkinter_id": None }}, { "$sample": { "size": number_of_squares }}, { "$count": "total"}]) # returns total number of parent Squareverse coordinates that don't have a tkinter ID (not occupied)
        # .find({"occupied": "false"})
        #.limit(number_of_squares)
        # results = list(dbCollection.find({"occupied": "false"}).limit(number_of_squares))
        # result_list = list(results)
        
        # pprint.pprint(totals[0])
        
        try:

            if available_coordinates.next()["total"] != 0:
                
                available_coordinates = dbCollection.aggregate([{ "$match": { "tkinter_id": None }}, { "$sample": { "size": number_of_squares }}])

                return free_space, available_coordinates
            
            else:
            
                free_space = False
                
                print("No results found!")
                return free_space, available_coordinates
                

        except:

            print("No next cursor")


    def get_available_child_squareverse_coordinates(self, number_of_squares, parent_square_tkinter_id):

        # dbCollection = self.db.squareverse_coordinates
        # free_space = True

        available_coordinates = self.db[f"squareverse_coordinates_{parent_square_tkinter_id}"].aggregate([{ "$match": { "child_square_id": None }}, { "$sample": { "size": number_of_squares }}])
        return available_coordinates
        # .find({"occupied": "false"})
        #.limit(number_of_squares)
        # results = list(dbCollection.find({"occupied": "false"}).limit(number_of_squares))
        # result_list = list(results)
        
        # pprint.pprint(totals[0])
        
        # try:

        #     if totals.next()["total"] != 0:
                
        #         results = dbCollection.aggregate([{ "$match": { "occupied": False }}, { "$sample": { "size": number_of_squares } }])

        #         return free_space, results
            
        #     else:
            
        #         free_space = False
                
        #         print("No results found!")
        #         return free_space, results
                

        # except:

        #     print("No next cursor")



    # def get_available_coordinates_testing(self):

    #     dbCollection = self.db.squareverse_coordinates
    #     free_space = True

    #     totals = dbCollection.aggregate([{ "$match": { "occupied": False }}, { "$sample": { "size": 5 }}, { "$count": "total"}])
        
    #     try:

    #      pprint.pprint(totals.next()["total"])

    #     except:

    #         print("No next cursor")


    def get_child_square_coordinates(self, child_square_ids, parent_square_tkinter_id):

        # print(f"\nDEBUG: Child Square IDs: {child_square_ids}\n") # DEBUG
        
        child_square_coordinates = self.db[f"squareverse_coordinates_{parent_square_tkinter_id}"].find({ "child_square_id": { "$in": child_square_ids }})

        # # DEBUG
        # for c in child_square_coordinates:

        #     print(f"\nChild Square coordinates\n")
        #     pprint.pprint(c)

        return child_square_coordinates


    # returns which direction has the largest number of child Squares
    def count_child_square_coordinates(self, child_squareverse_center_point_coordinate, parent_square_tkinter_id):

        # print(f"\nChild Squareverse center point coordinates: {child_squareverse_center_point_coordinate}\n") # DEBUG
        
        child_square_coordinates_count = self.db[f"squareverse_coordinates_{parent_square_tkinter_id}"].aggregate([
            { "$facet": {
                "up": [
                    { "$match": { "top_left_corner_y": { "$lt": child_squareverse_center_point_coordinate }, "child_square_id": { "$ne": None }}},
                    { "$count": "total" }
                ],
                "down": [
                    { "$match": { "top_left_corner_y": { "$gte": child_squareverse_center_point_coordinate }, "child_square_id": { "$ne": None }}},
                    # {"$match": {"$gte": ["top_left_corner_y", child_squareverse_center_point_coordinate]}},
                    { "$count": "total" }
                ],
                "left": [
                    { "$match": { "top_left_corner_x": { "$lt": child_squareverse_center_point_coordinate }, "child_square_id": { "$ne": None }}},
                    # {"$match": {"$lt": ["top_left_corner_x", child_squareverse_center_point_coordinate]}},
                    { "$count": "total" }
                ],
                "right": [
                    { "$match": { "top_left_corner_x": { "$gte": child_squareverse_center_point_coordinate }, "child_square_id": { "$ne": None }}},
                    # {"$match": {"$gte": ["top_left_corner_x", child_squareverse_center_point_coordinate]}},
                    { "$count": "total" }
                ],
            }},
            { "$project": {
                "up": { "$arrayElemAt": [ "$up.total", 0 ]},
                "down": { "$arrayElemAt": [ "$down.total", 0 ]},
                "left": { "$arrayElemAt": [ "$left.total", 0 ]},
                "right": { "$arrayElemAt": [ "$right.total", 0 ]},
            }}
        ])
        
        for coordinate_count in child_square_coordinates_count:

            # print(f"Child Squares coordinate count: {coordinate_count}\n") # DEBUG
            total_coordinate_count = coordinate_count

        return total_coordinate_count
        
        
        
        # db.collection.aggregate([
        #     { "$facet": {
        #         "Total": [
        #         { "$match" : { "ReleaseDate": { "$exists": true }}},
        #         { "$count": "Total" },
        #         ],
        #         "Released": [
        #         { "$match" : {"ReleaseDate": { "$exists": true, "$nin": [""] }}},
        #         { "$count": "Released" }
        #         ],
        #         "Unreleased": [
        #         { "$match" : {"ReleaseDate": { "$exists": true, "$in": [""] }}},
        #         { "$count": "Unreleased" }
        #         ]
        #     }},
        #     { "$project": {
        #         "Total": { "$arrayElemAt": ["$Total.Total", 0] },
        #         "Released": { "$arrayElemAt": ["$Released.Released", 0] },
        #         "Unreleased": { "$arrayElemAt": ["$Unreleased.Unreleased", 0] }
        #     }}
        # ])




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


    def update_parent_square_coordinates(self, parent_square, selected_direction_coordinates):

        dbCollection = self.db.squareverse_coordinates

        dbCollection.bulk_write( [

            UpdateOne({ 'tkinter_id': parent_square.tkinter_id }, { '$set': { 'tkinter_id': None, 'previous_direction': None }}),
            UpdateOne({ '_id': selected_direction_coordinates["_id"] }, { '$set': {'tkinter_id': parent_square.tkinter_id , 'previous_direction': parent_square.selected_direction}})

        ])


    def update_child_square_coordinates(self, parent_square, child_square_coordinate, selected_direction, selected_direction_coordinates):

        # dbCollection = self.db.squareverse_coordinates

        self.db[f"squareverse_coordinates_{parent_square.tkinter_id}"].bulk_write( [

            UpdateOne({ 'child_square_id': child_square_coordinate["child_square_id"] }, { '$set': {'child_square_id': None, "previous_direction": None }}),
            UpdateOne({ '_id': selected_direction_coordinates["_id"] }, { '$set': { 'child_square_id': child_square_coordinate["child_square_id"], "previous_direction": selected_direction }})

        ])


    
    
    def update_mongodb(self, mongo_query, updated_value):

        dbCollection = self.db.squareverse_coordinates

        dbCollection.update_one(mongo_query, updated_value)


    def update_mongodb_child_squareverse(self, mongo_query, updated_value, parent_square_id):

        # dbCollection = self.db.squareverse_coordinates

        self.db[f"squareverse_coordinates_{parent_square_id}"].update_one(mongo_query, updated_value)



    def collision_check_parent_squareverse(self, parent_square, parent_squareverse, selected_direction):

        '''Accepts coordinates for selected direction, returns False and coordinates for selected direction if collision not detected'''

        dbCollection = self.db.squareverse_coordinates
        
        selected_direction_coordinates = None
        collision_detected = False

        # # DEBUG
        # print(f"\nDEBUG: Current top-left corner coordinates for parent Square {parent_square.tkinter_id} before moving:\n")
        # print(f"X: {parent_square.body.p1.x}\n")
        # print(f"Y: {parent_square.body.p1.y}\n")
        # #

        top_left_corner_x_after_moving = parent_square.body.p1.x + parent_squareverse.valid_directions[selected_direction]['x']
        top_left_corner_y_after_moving = parent_square.body.p1.y + parent_squareverse.valid_directions[selected_direction]['y']
        # top_left_corner_x_after_moving = square.top_left_corner_x + squareverse.valid_directions[selected_direction]['x']
        # top_left_corner_y_after_moving = square.top_left_corner_y + squareverse.valid_directions[selected_direction]['y']
        
        # # DEBUG
        # print(f"\nDEBUG: Top-left corner coordinates after modifying parent Square current coordinates using selected direction:\n")
        # print(f"X: {top_left_corner_x_after_moving}\n")
        # print(f"Y: {top_left_corner_y_after_moving}\n")
        # #

        if top_left_corner_x_after_moving < parent_squareverse.squareverse_grid_spacing or top_left_corner_y_after_moving < parent_squareverse.squareverse_grid_spacing or top_left_corner_x_after_moving > parent_squareverse.squareverse_size or top_left_corner_y_after_moving > parent_squareverse.squareverse_size:

            # print(f"\nDEBUG: Squareverse border detected!\n") # DEBUG
            
            # square.number_of_collisions = square.number_of_collisions + 1
            collision_detected = True
            return collision_detected, selected_direction_coordinates

            
        else:

            # STOPPED HERE
            selected_direction_coordinates = dbCollection.find_one({ "$and": [{ "top_left_corner_x": top_left_corner_x_after_moving }, { "top_left_corner_y": top_left_corner_y_after_moving }]})

            # print(f"\nDEBUG: Selected direction coordinates: {selected_direction_coordinates}\n") # DEBUG
            
            if selected_direction_coordinates["tkinter_id"] != None:

                 collision_detected = True
                 return collision_detected, selected_direction_coordinates

            else:

                return collision_detected, selected_direction_coordinates
            
            
        #     collision_count = 0
        #     collisions = dbCollection.aggregate([
        #         { 
        #             "$match": {
        #                 "$and":[
        #                     { "top_left_corner_x": top_left_corner_x_after_moving },
        #                     { "top_left_corner_y": top_left_corner_y_after_moving },
        #                     { "tkinter_id": { "$exists": True }}
        #                 ]
        #             }
        #         },
        #         { 
        #             "$count": "total"
        #         }
        #     ])
            

        #     for collision in collisions:

        #         collision_count = collision["total"]

        #     if collision_count >= 1:
        
        #         # square.number_of_collisions = square.number_of_collisions + 1
        #         collision_detected = True

        # return collision_detected


    def collision_check_child_squareverse(self, child_squareverse, parent_square, child_square_coordinate, selected_direction):

        '''Accepts coordinates for selected direction, returns True if collision detected'''

        selected_direction_coordinates = None

        collision_detected = False
        top_left_corner_x_after_moving = child_square_coordinate["top_left_corner_x"] + child_squareverse.valid_directions[selected_direction]['x']
        top_left_corner_y_after_moving = child_square_coordinate["top_left_corner_y"] + child_squareverse.valid_directions[selected_direction]['y']
        # top_left_corner_x_after_moving = square.top_left_corner_x + squareverse.valid_directions[selected_direction]['x']
        # top_left_corner_y_after_moving = square.top_left_corner_y + squareverse.valid_directions[selected_direction]['y']
        
        
        if top_left_corner_x_after_moving < child_squareverse.squareverse_grid_spacing or top_left_corner_y_after_moving < child_squareverse.squareverse_grid_spacing or top_left_corner_x_after_moving > child_squareverse.squareverse_size or top_left_corner_y_after_moving > child_squareverse.squareverse_size:

            collision_detected = True
            return collision_detected, selected_direction_coordinates

            # print(f"Squareverse border detected!\n") # DEBUG
        else:

            selected_direction_coordinates = self.db[f"squareverse_coordinates_{parent_square.tkinter_id}"].find_one({ "$and": [{ "top_left_corner_x": top_left_corner_x_after_moving }, { "top_left_corner_y": top_left_corner_y_after_moving }]})

            if selected_direction_coordinates["child_square_id"] != None:

                 collision_detected = True
                 return collision_detected, selected_direction_coordinates

            else:

                return collision_detected, selected_direction_coordinates




            
            
        #     collision_count = 0
        #     collisions = self.db[f"squareverse_coordinates_{parent_square.tkinter_id}"].aggregate([
        #         { 
        #             "$match": {
        #                 "$and":[
        #                     { "top_left_corner_x": top_left_corner_x_after_moving },
        #                     { "top_left_corner_y": top_left_corner_y_after_moving },
        #                     { "occupied": True }
        #                 ]
        #             }
        #         },
        #         { 
        #             "$count": "total"
        #         }
        #     ])
            

        #     for collision in collisions:

        #         collision_count = collision["total"]

        #     if collision_count >= 1:
        
        #         collision_detected = True

        # return collision_detected





            # print(f"Squares found in selected direction: {total_results}\n")
            # print(result)
        # for result in results:

        #     pprint.pprint(result)
        # results = dbCollection.find_one({ "top_left_corner_x": top_left_corner_x_after_moving }, { "top_left_corner_y": top_left_corner_y_after_moving }, { "occupied": True })
        # more_results = results.next()["total"]
        # pprint.pprint(results)

        # logic for detecting Squareverse borders
        # print(f"\n{type(square)}") # debug

       
            
        

        



    def collision_check_testing(self, square, squareverse, selected_direction):

        dbCollection = self.db.squareverse_coordinates
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




# mongo.create_squareverse_coordinates(10, 31)
# mongo.get_available_coordinates_testing()

# mongo.insert_valid_directions(5)

# mongo.delete_valid_directions()
# mongo.db.valid_directions.drop_many({})
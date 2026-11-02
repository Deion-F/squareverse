"""The tests check the physics at the tuning they were written for, not whatever the app's starting defaults are."""

from sv import config

config.GRAVITY_REACH = 60.0
config.GRAVITY_SCALE = 1.0
config.ORBIT_EDGE_SPEED = 4.0
config.SUPER_EXPLODE_MASS = 7_500_000
config.RADIATION_ON = False

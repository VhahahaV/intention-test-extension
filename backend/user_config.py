import configparser
import os

global_config = configparser.ConfigParser()

global_config.read(os.path.join(os.path.dirname(__file__), 'config.ini'))

#      _____         __        __                               ____                                        __
#     / ___/ ____ _ / /____   / /_   __  __ _____ ____ _       / __ \ ___   _____ ___   ____ _ _____ _____ / /_
#     \__ \ / __ `// //_  /  / __ \ / / / // ___// __ `/      / /_/ // _ \ / ___// _ \ / __ `// ___// ___// __ \
#    ___/ // /_/ // /  / /_ / /_/ // /_/ // /   / /_/ /      / _, _//  __/(__  )/  __// /_/ // /   / /__ / / / /
#   /____/ \__,_//_/  /___//_.___/ \__,_//_/    \__, /      /_/ |_| \___//____/ \___/ \__,_//_/    \___//_/ /_/
#                                              /____/
#   Salzburg Research ForschungsgesmbH
#   Armin Niedermueller, Christoph Schranz

#   OPC UA Adapter for the Cluster Messaging System
#   The purpose of this OPCUA client is to call the provided methods of the ConveyorBelt and Robot and
#   forward their statues into the Messaging System

import os
import sys
import time
import pytz
import json
import socket
import inspect
import logging
import threading
from datetime import datetime

from opcua import Client

# confluent_kafka is based on librdkafka, details in requirements.txt
from panta_rhei.client.digital_twin_client import DigitalTwinClient

INTERVAL = 0.25
BIG_INTERVALL = 10

__author__ = "Salzburg Research"
__version__ = "0.1"
__date__ = "7 Juni 2019"
__email__ = "christoph.schranz@salzburgresearch.at"
__status__ = "Development"

# Panta Rhei configuration
CLIENT_NAME = os.environ.get("CLIENT_NAME", "opcua-adapter")
SYSTEM_NAME = os.environ.get("SYSTEM_NAME", "test")  # "at.srfg.iot.dtz")  # setthose configs in docker-compose.yml
SENSORTHINGS_HOST = os.environ.get("SENSORTHINGS_HOST", "localhost:8082")
BOOTSTRAP_SERVERS = os.environ.get("BOOTSTRAP_SERVERS", "192.168.48.71:9092,192.168.48.72:9092,192.168.48.73:9092,192.168.48.74:9092,192.168.48.75:9092")

# Client server
CLIENT_PIXTEND_SERVER = os.environ.get("CLIENT_URL_PIXTEND_SERVER", "opc.tcp://192.168.48.42:4840/freeopcua/server/")
CLIENT_PANDA_SERVER = os.environ.get("CLIENT_URL_PANDA_SERVER", "opc.tcp://192.168.48.41:4840/freeopcua/server/")

CLIENT_SIGVIB_SERVER = os.environ.get("CLIENT_URL_SIGVIB_SERVER", "opc.tcp://192.168.48.55:4842/freeopcua/server/")
CLIENT_SIGSHELF_SERVER = os.environ.get("CLIENT_URL_SIGSTORE_SERVER", "opc.tcp://192.168.48.53:4842/freeopcua/server/")

CLIENT_FHS_SERVER = os.environ.get("CLIENT_URL_FHS_SERVER", "opc.tcp://192.168.10.102:4840")
CLIENT_PSEUDO_FHS_SERVER = os.environ.get("CLIENT_URL_PSEUDO_FHS_SERVER", "opc.tcp://192.168.48.44:4840/freeopcua/server/")

# OPC-UA configuration
last_state = dict({"PandaRobot.State": None,
                   "Conbelt.State": None,
                   "Conbelt.Dist": None})

# client_urlpanda_server = Client(CLIENT_URL_PANDA_SERVER)
# client_pixtend_server = Client(CLIENT_URL_PIXTEND_SERVER)
# client_fhs_server = Client(CLIENT_URL_FHS_SERVER)
# client_pseudo_fhs_server = Client(CLIENT_URL_PSEUDO_FHS_SERVER)

# client_panda_server.connect()
# client_pixtend_server.connect()
# client_fhs_server.connect()
# client_pseudo_fhs_server.connect()

# use freeopcua service to investigate the trees
# root_panda = client_panda.get_root_node()
# root_pixtend = client_pixtend_server.get_root_node()


class PiXtendAdapter:
    # Class where current stati and timeouts of all metrics in the pixtend are stored
    def __init__(self):
        start_time = time.time()
        self.conbelt_state = "initial state"
        self.conbelt_state_to = start_time + BIG_INTERVALL
        self.conbelt_dist = float("-inf")
        self.conbelt_dist_to = start_time + BIG_INTERVALL

        self.busy_light = "initial state"
        self.busy_light_to = start_time + BIG_INTERVALL
        self.conbelt_moving = "initial state"
        self.conbelt_moving_to = start_time + BIG_INTERVALL

        self.root_pixtend = None

    def start_loop(self):
        interrupted = False
        while not interrupted:
            client_pixtend_server = None
            try:
                client_pixtend_server = Client(CLIENT_PIXTEND_SERVER)
                client_pixtend_server.connect()
                self.root_pixtend = client_pixtend_server.get_root_node()
                logger.info("Started PiXtend loop")

                while True:
                    # upsert_panda_state()
                    self.fetch_conbelt_state()
                    self.fetch_conbelt_dist()
                    # self.fetch_light_state() #TODO doesn't work right now
                    # self.fetch_belt_state()  #TODO what is that metric?
                    time.sleep(INTERVAL)
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt, gracefully closing")
                if client_pixtend_server:
                    client_pixtend_server.disconnect()
                pr_client.disconnect()
                interrupted = True

            except Exception as e:
                logger.warning("Exception PiXtend loop, Reconnecting in 60 seconds.", e)
                time.sleep(60)

    def fetch_conbelt_state(self):
        conbelt_state = self.root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:ConBeltState"]).get_data_value()
        value = conbelt_state.Value.Value
        ts = conbelt_state.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat()
        if (value != self.conbelt_state):  # or (time.time() >= self.conbelt_state_to):
            # self.conbelt_state_to = time.time() + BIG_INTERVALL
            self.conbelt_state = value
            logger.info("conveyor_belt_state: {}".format(value))
            pr_client.produce(quantity="conveyor_belt_state", result=value, timestamp=ts)

    def fetch_conbelt_dist(self):
        conbelt_dist = self.root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:ConBeltDist"]).get_data_value()
        value = float(conbelt_dist.Value.Value)
        ts = conbelt_dist.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat()
        if (value != self.conbelt_dist):  # or (time.time() >= self.conbelt_dist_to):
            # self.conbelt_dist_to = time.time() + BIG_INTERVALL
            self.conbelt_dist = value
            logger.info("conveyor_belt_position: {}".format(value))
            pr_client.produce(quantity="conveyor_belt_position", result=value, timestamp=ts)

    def fetch_light_state(self):
        pass
        # light_state = self.root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:SwitchBusyLight"])
        # print(light_state)
        # print(dict(light_state))
        # value = float(light_state.get_value().Value.Value)
        # ts = light_state.get_value().SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat()
        # print(light_state)
        # if (value != self.conbelt_dist) or (time.time() >= self.conbelt_dist_to):
        #     self.conbelt_dist_to = time.time() + BIG_INTERVALL
        #     self.conbelt_dist = value
        #     logger.info("conveyor_belt_position: {}".format(value))
        #     # pr_client.produce(quantity="conveyor_belt_position", result=value, timestamp=ts)

    def fetch_belt_state(self):
        conbelt_moving = self.root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:ConBeltMoving"]).get_data_value()
        value = float(conbelt_moving.Value.Value)
        ts = conbelt_moving.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat()

        if (value != self.conbelt_moving): # or (time.time() >= self.conbelt_moving_to):
            # self.conbelt_moving_to = time.time() + BIG_INTERVALL
            self.conbelt_moving = value
            logger.info("conveyor_belt_moving: {}".format(value))
        #     # pr_client.produce(quantity="conveyor_belt_position", result=value, timestamp=ts)


# TODO do we need that or is that already impemented via ROS-kafka-adapter
class PandaAdapter:
    # Class where current stati and timeouts of all metrics in the panda are stored
    def __init__(self):
        start_time = time.time()
        self.panda_state = "initial state"
        self.panda_state_to = start_time + BIG_INTERVALL
        self.root_panda = None

    def start_loop(self):
        interrupted = False
        while not interrupted:
            client_panda_server = None
            try:
                client_panda_server = Client(CLIENT_PANDA_SERVER)
                client_panda_server.connect()
                self.root_panda = client_panda_server.get_root_node()
                logger.info("Started Panda loop")

                while True:
                    self.fetch_panda_state()
                    time.sleep(INTERVAL)
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt, gracefully closing")
                if client_panda_server:
                    client_panda_server.disconnect()
                interrupted = True

            except Exception as e:
                # Suppressing warning, as the panda runs only occasionally
                logger.warning("Exception Panda loop, Reconnecting in 60 seconds.", e)
                time.sleep(60)

    def fetch_panda_state(self):
        panda_state = self.root_panda.get_child(["0:Objects", "2:PandaRobot", "2:RobotState"]).get_data_value()
        # panda_temp_value = root_panda.get_child(["0:Objects", "2:PandaRobot", "2:RobotTempValue"]).get_data_value()
        value = panda_state.Value.Value
        ts = panda_state.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat()

        if (value != self.panda_state) or (time.time() >= self.panda_state_to):
            self.panda_state_to = time.time() + BIG_INTERVALL
            self.panda_state = value
            logger.info("panda state: {}".format(value))
            # pr_client.produce(quantity="conveyor_belt_position", result=value, timestamp=ts)  #


class SigmatekVibrationAdapter:
    # Class where current stati and timeouts of all metrics in the panda are stored
    def __init__(self):
        start_time = time.time()
        self.vib_x = float("-inf")
        self.vib_x_to = start_time + BIG_INTERVALL
        self.vib_y = float("-inf")
        self.vib_y_to = start_time + BIG_INTERVALL
        self.root_sig_vib = None

    def start_loop(self):
        interrupted = False
        while not interrupted:
            client_sigvib_server = None
            try:
                client_sigvib_server = Client(CLIENT_SIGVIB_SERVER)
                client_sigvib_server.connect()
                self.root_sig_vib = client_sigvib_server.get_root_node()
                logger.info("Started Sigmatek Vibration loop")
                while True:
                    # Send vibration if timeout is reached or difference exceeds 0.005m/s
                    self.fetch_vibration_x()
                    self.fetch_vibration_y()
                    time.sleep(INTERVAL)

            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt, gracefully closing")
                if client_sigvib_server:
                    client_sigvib_server.disconnect()
                pr_client.disconnect()
                interrupted = True

            except Exception as e:
                logger.warning("Exception Sigmatek Vibration loop, Reconnecting in 60 seconds.", e)
                time.sleep(60)

    def fetch_vibration_x(self):
        vib_x_data = self.root_sig_vib.get_child(["0:Objects", "2:Vibration_X.VibrationValue"]).get_data_value()
        value = vib_x_data.Value.Value
        # ts = vib_x_data.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat()

        if abs(value-self.vib_x > 0.005) or (time.time() >= self.vib_x_to):
            self.vib_x_to = time.time() + BIG_INTERVALL
            self.vib_x = value
            logger.debug("vibration x-axis: {}".format(value))
            pr_client.produce(quantity="robot_x_vibration", result=value)

    def fetch_vibration_y(self):
        vib_y_data = self.root_sig_vib.get_child(["0:Objects", "2:Vibration_Y.VibrationValue"]).get_data_value()
        value = vib_y_data.Value.Value
        # ts = vib_y_data.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat()

        if abs(value-self.vib_y) > 0.005 or (time.time() >= self.vib_y_to):
            self.vib_y_to = time.time() + BIG_INTERVALL
            self.vib_y = value
            logger.debug("vibration y-axis: {}".format(value))
            pr_client.produce(quantity="robot_y_vibration", result=value)


class SigmatekShelfAdapter:
    # Class where current stati and timeouts of all metrics in the panda are stored
    # Fetches all shelf 9 stati, sending each one only when value changes and then the old and new one to improve
    # the interpolation
    def __init__(self):
        start_time = time.time()
        self.shelf = [-1]*9
        self.shelf_to = [start_time + BIG_INTERVALL]*9
        self.root_sig_shelf = None

    def start_loop(self):
        interrupted = False
        while not interrupted:
            client_sigshelf_server = None
            try:
                client_sigshelf_server = Client(CLIENT_SIGSHELF_SERVER)
                client_sigshelf_server.connect()
                self.root_sig_shelf = client_sigshelf_server.get_root_node()
                logger.info("Started Sigmatek Shelf loop")
                while True:
                    self.fetch_shelf_data()
                    time.sleep(INTERVAL)

            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt, gracefully closing")
                if client_sigshelf_server:
                    client_sigshelf_server.disconnect()
                pr_client.disconnect()
                interrupted = True

            except Exception as e:
                logger.warning("Exception Sigmatek Shelf loop, Reconnecting in 60 seconds.", e)
                time.sleep(60)

    def fetch_shelf_data(self):
        # Fetches all shelf 9 stati, sending each one only when value changes and then the old and new one to improve
        # the interpolation
        shelf_stati = [-1]*9
        for i in range(9):
            shelf_stati[i] = self.root_sig_shelf.get_child(["0:Objects", "2:Shelf{}.LEDServer".format(i+1)]
                                                           ).get_data_value()
        values = [status.Value.Value for status in shelf_stati]
        ts = max([status.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat() for status in shelf_stati])
        for i in range(9):
            if values[i] != self.shelf[i]:
                # Sending old status with timestamp-INTERVALL and then current status, unless it's initial
                if self.shelf[i] != -1:
                    logger.info("new status in shelf {}: {}".format(i+1, self.shelf[i]))
                    pr_client.produce(quantity="shelf_status_{}".format(i+1), result=self.shelf[i],
                                      timestamp=ts-INTERVAL)
                self.shelf[i] = values[i]
                logger.info("new status in shelf {}: {}".format(i+1, self.shelf[i]))
                pr_client.produce(quantity="shelf_status_{}".format(i+1), result=self.shelf[i], timestamp=ts)


if __name__ == "__main__":
    logger = logging.getLogger("OPC-UA-Adapter_Logger")
    logger.setLevel(logging.INFO)
    logging.basicConfig()
    logger.info("OPC-UA Adapter for the Messaging system was started on host: {}"
                .format(socket.gethostname()))

    # Get dirname from inspect module
    filename = inspect.getframeinfo(inspect.currentframe()).filename
    dirname = os.path.dirname(os.path.abspath(filename))
    INSTANCES = os.path.join(dirname, "instances.json")
    MAPPINGS = os.path.join(dirname, "ds-mappings.json")

    config = {"client_name": CLIENT_NAME,
              "system": SYSTEM_NAME,
              "kafka_bootstrap_servers": BOOTSTRAP_SERVERS,
              "gost_servers": SENSORTHINGS_HOST}
    pr_client = DigitalTwinClient(**config)
    pr_client.register_new(instance_file=INSTANCES)
    # pr_client.register_existing(mappings_file=MAPPINGS)
    logger.info("Panta Rhei Client was created, ready to stream")

    # Create a adapter for each opc ua server and start them
    pixtend_client = PiXtendAdapter()
    pixtend_thread = threading.Thread(name="pixtend_thread", target=pixtend_client.start_loop, args=())
    pixtend_thread.start()

    panda_client = PandaAdapter()
    panda_thread = threading.Thread(name="panda_thread", target=panda_client.start_loop, args=())
    panda_thread.start()

    sigvib_client = SigmatekVibrationAdapter()
    sigvib_thread = threading.Thread(name="sigvib_thread", target=sigvib_client.start_loop, args=())
    sigvib_thread.start()

    sigshelf_client = SigmatekShelfAdapter()
    sigshelf_thread = threading.Thread(name="sigshelf_client", target=sigshelf_client.start_loop, args=())
    sigshelf_thread.start()

    # try:
    #     while True:
    #         time.sleep(0.1)
    #
    # except KeyboardInterrupt:
    #     logger.info("KeyboardInterrupt, gracefully closing")
    #     pr_client.disconnect()
    #     # pixtend_thread.join()
    #     # panda_thread.join()
    #     # sigvib_thread.join()

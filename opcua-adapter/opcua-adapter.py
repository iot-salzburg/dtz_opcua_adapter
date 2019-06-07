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
SYSTEM_NAME = os.environ.get("SYSTEM_NAME", "test-topic")  # "at.srfg.iot.dtz"
SENSORTHINGS_HOST = os.environ.get("SENSORTHINGS_HOST", "localhost:8082")
BOOTSTRAP_SERVERS = os.environ.get("BOOTSTRAP_SERVERS", "192.168.48.71:9092,192.168.48.72:9092,192.168.48.73:9092,192.168.48.74:9092,192.168.48.75:9092")

# Client server
CLIENT_URL_PANDA_SERVER = os.environ.get("CLIENT_URL_PANDA_SERVER", "opc.tcp://192.168.48.41:4840/freeopcua/server/")
CLIENT_URL_PIXTEND_SERVER = os.environ.get("CLIENT_URL_PIXTEND_SERVER",
                                           "opc.tcp://192.168.48.42:4840/freeopcua/server/")
CLIENT_URL_FHS_SERVER = os.environ.get("CLIENT_URL_FHS_SERVER", "opc.tcp://192.168.10.102:4840")
CLIENT_URL_PSEUDO_FHS_SERVER = os.environ.get("CLIENT_URL_PSEUDO_FHS_SERVER",
                                              "opc.tcp://192.168.48.44:4840/freeopcua/server/")

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
            try:
                client_pixtend_server = Client(CLIENT_URL_PIXTEND_SERVER)
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
                pr_client.disconnect()
                interrupted = True

            except Exception as e:
                logger.warning("Exception PiXtend loop, Reconnecting in 60 seconds.", e)
                time.sleep(60)

    def fetch_conbelt_state(self):
        conbelt_state = self.root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:ConBeltState"]).get_data_value()
        value = conbelt_state.Value.Value
        ts = conbelt_state.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat()

        if (value != self.conbelt_state) or (time.time() >= self.conbelt_state_to):
            self.conbelt_state_to = time.time() + BIG_INTERVALL
            self.conbelt_state = value
            logger.info("conveyor_belt_state: {}".format(value))
            pr_client.produce(quantity="conveyor_belt_state", result=value, timestamp=ts)

    def fetch_conbelt_dist(self):
        conbelt_dist = self.root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:ConBeltDist"]).get_data_value()
        value = float(conbelt_dist.Value.Value)
        ts = conbelt_dist.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat()
        print(value)
        if (value != self.conbelt_dist) or (time.time() >= self.conbelt_dist_to):
            self.conbelt_dist_to = time.time() + BIG_INTERVALL
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

        if (value != self.conbelt_moving) or (time.time() >= self.conbelt_moving_to):
            self.conbelt_moving_to = time.time() + BIG_INTERVALL
            self.conbelt_moving = value
            logger.info("conveyor_belt_moving: {}".format(value))
        #     # pr_client.produce(quantity="conveyor_belt_position", result=value, timestamp=ts)



# def upsert_panda_state():
#     panda_state = root_panda.get_child(["0:Objects", "2:PandaRobot", "2:RobotState"]).get_data_value()
#     # panda_temp_value = root_panda.get_child(["0:Objects", "2:PandaRobot", "2:RobotTempValue"]).get_data_value()
#     value = panda_state.Value.Value
#     if value != last_state["PandaRobot.State"]:
#         last_state["PandaRobot.State"] = value
#         data = {"name": "dtz.PandaRobot.RobotState",
#                 "phenomenonTime": panda_state.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat(),
#                 "resultTime": datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat(),
#                 "result": None,
#                 "parameters": dict({"state": value})}
#         # print("publish panda state")
#         publish_message(data)

def publish_message(message):
    # message = transform_name_to_id(message)
    print(message)
    # Trigger any available delivery report callbacks from previous produce() calls
    # producer.poll(0)
    # producer.produce(KAFKA_TOPIC_metric, json.dumps(message).encode('utf-8'),
    #                  key=KAFKA_GROUP_ID, callback=delivery_report)


def delivery_report(err, msg):
    """ Called once for each message produced to indicate delivery result.
        Triggered by poll() or flush(). """
    if err is not None:
        print('Message delivery failed: {}, {}, {}'.format(err, msg.topic(), msg.value()))
    # else:
    #     print('Message delivered to {} [{}] with content: {}'.format(msg.topic(), msg.partition(),
    #                                                                  msg.value()))


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



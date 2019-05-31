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
from datetime import datetime

from opcua import Client
from confluent_kafka import Producer, KafkaError

# confluent_kafka is based on librdkafka, details in requirements.txt
from panta_rhei.client.digital_twin_client import DigitalTwinClient

INTERVAL = 0.25
BIG_INTERVALL = 10

__author__ = "Salzburg Research"
__version__ = "0.1"
__date__ = "31 May 2019"
__email__ = "christoph.schranz@salzburgresearch.at"
__status__ = "Development"

# Panta Rhei configuration
CLIENT_NAME = os.environ.get("CLIENT_NAME", "opcua-adapter")
SYSTEM_NAME = os.environ.get("SYSTEM_NAME", "test-topic")  # "at.srfg.iot.dtz"
SENSORTHINGS_HOST = os.environ.get("SENSORTHINGS_HOST", "localhost:8082")
BOOTSTRAP_SERVERS = os.environ.get("BOOTSTRAP_SERVERS", "192.168.48.71:9092,192.168.48.72:9092,192.168.48.73:9092,192.168.48.74:9092,192.168.48.75:9092")

# OPC-UA configuration
last_state = dict({"PandaRobot.State": None,
                   "Conbelt.State": None,
                   "Conbelt.Dist": None})

# client_panda = Client("opc.tcp://192.168.48.41:4840/freeopcua/server/")
client_pixtend = Client("opc.tcp://192.168.48.42:4840/freeopcua/server/")
# client_panda.connect()
client_pixtend.connect()


# use freeopcua servie to investigate the trees
# root_panda = client_panda.get_root_node()
root_pixtend = client_pixtend.get_root_node()
start_time = time.time()

class opcua_status:
    def __init__(self):
        self.conbelt_state_to = start_time + BIG_INTERVALL
        self.conbelt_dist_to = start_time + BIG_INTERVALL
        self.panda_state_to = start_time + BIG_INTERVALL

def start():
    try:
        while True:
            # upsert_panda_state()
            upsert_conbelt_state()
            upsert_conbelt_dist()
            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        kafka_logger("KeyboardInterrrupt, gracefully closing", level="INFO")
    finally:
        pr_client.disconnect()

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

def upsert_conbelt_state():
    conbelt_state = root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:ConBeltState"]).get_data_value()
    value = conbelt_state.Value.Value
    ts = conbelt_state.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat()

    if (value != last_state["Conbelt.State"]) or (time.time() >= opcua_status.conbelt_dist_to):
        if time.time() >= opcua_status.conbelt_dist_to:
            opcua_status.conbelt_dist_to += BIG_INTERVALL
        else:
            opcua_status.conbelt_dist_to = time.time() + BIG_INTERVALL

        last_state["Conbelt.State"] = value

        print("conveyor_belt_state: {}".format(value))
        pr_client.produce(quantity="conveyor_belt_state", result=value, timestamp=ts)

def upsert_conbelt_dist():
    conbelt_dist = root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:ConBeltDist"]).get_data_value()
    value = float(conbelt_dist.Value.Value)
    ts = conbelt_dist.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat()

    if (value != last_state["Conbelt.Dist"]) or (time.time() >= opcua_status.conbelt_state_to):
        if time.time() >= opcua_status.conbelt_state_to:
            opcua_status.conbelt_state_to += BIG_INTERVALL
        else:
            opcua_status.conbelt_state_to = time.time() + BIG_INTERVALL

        last_state["Conbelt.Dist"] = value

        print("conveyor_belt_position: {}".format(value))
        pr_client.produce(quantity="conveyor_belt_position", result=value, timestamp=ts)


def transform_name_to_id(data):
    data["Datastream"] = dict({"@iot.id": DATASTREAM_MAPPING[data["name"]]})
    x = data.pop("name")
    return data


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
        kafka_logger('Message delivery failed: {}, {}, {}'.format(err, msg.topic(), msg.value()))
    # else:
    #     print('Message delivered to {} [{}] with content: {}'.format(msg.topic(), msg.partition(),
    #                                                                  msg.value()))


def kafka_logger(payload, level="debug"):
    """
    Publish the canonical data format (Version: i-maintenance first iteration)
    to the Kafka Bus.
    Keyword argument:
    :param payload: message content as json or string
    :param level: log-level
    :return: None
    """
    # print(level, payload)
    # return
    message = {"Datastream": "dtz.opcua-adapter.logging",
               "phenomenonTime": datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat(),
               "result": payload,
               "level": level,
               "host": socket.gethostname()}

    print("Level: {} \tMessage: {}".format(level, payload))
    # producer.poll(0)
    # producer.produce(KAFKA_TOPIC_logging, json.dumps(message).encode('utf-8'),
    #                  key=KAFKA_GROUP_ID, callback=logger_delivery_report)


def logger_delivery_report(err, msg):
    """ Called once for each message produced to indicate delivery result.
        Triggered by poll() or flush(). """
    if err is not None:
        kafka_logger('Message delivery failed: {}, {}, {}'.format(err, msg.topic(), msg.value()))
    else:
        print('Message delivered to {} [{}] with content: {}'.format(msg.topic(), msg.partition(),
                                                                     msg.value()))


if __name__ == "__main__":
    # kafka_logger("OPC-UA Adapter for the Messaging system was started on host: {}"
    #              .format(socket.gethostname()), level="INFO")
    # kafka_logger("Kafka producer for was created, ready to stream", level="INFO")

    opcua_status = opcua_status()
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

    start()

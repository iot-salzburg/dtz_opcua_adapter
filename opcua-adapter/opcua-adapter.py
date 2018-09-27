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
from datetime import datetime
from opcua import Client
from confluent_kafka import Producer, KafkaError

INTERVAL = 0.25

# Messaging System Configurations
BOOTSTRAP_SERVERS = '192.168.48.81:9092' #,192.168.48.82:9092,192.168.48.83:9092'  # TODO fix that node error
KAFKA_GROUP_ID = "opc-adapter"
KAFKA_TOPIC_metric = "dtz.sensorthings"
KAFKA_TOPIC_logging = "dtz.logging"
SENSORTHINGS_HOST = "192.168.48.81"
SENSORTHINGS_PORT = "8084"

# sensorthings status
dir_path = os.path.dirname(os.path.realpath(__file__))
datastream_file = os.path.join(dir_path, "sensorthings", "id-structure.json")

sys.path.insert(0, "..")  # TODO fia wos?


last_state = dict({"PandaRobot.State": None,
                        "Conbelt.State": None,
                        "Conbelt.Dist": None})
connected = False
while not connected:
    try:
        client_panda = Client("opc.tcp://192.168.48.41:4840/freeopcua/server/")
        client_pixtend = Client("opc.tcp://192.168.48.42:4840/freeopcua/server/")
        client_panda.connect()
        client_pixtend.connect()
        connected = True
    except:
        print("No connection found")
        time.sleep(10)

# use freeopcua servie to investigate the trees
root_panda = client_panda.get_root_node()
root_pixtend = client_pixtend.get_root_node()

with open(datastream_file) as ds_file:
    DATASTREAM_MAPPING = json.load(ds_file)["Datastreams"]

# Messaging System
conf = {'bootstrap.servers': BOOTSTRAP_SERVERS}
producer = Producer(**conf)


def disconnect():
    client_panda.disconnect()
    client_pixtend.disconnect()
    # Wait for any outstanding messages to be delivered and delivery report
    # callbacks to be triggered.
    producer.flush()


def start():
    try:
        while True:
            upsert_panda_state()
            upsert_conbelt_state()
            upsert_conbelt_dist()
            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        kafka_logger("KeyboardInterrrupt, gracefully closing", level="INFO")
    finally:
        disconnect()

def upsert_panda_state():
    panda_state = root_panda.get_child(["0:Objects", "2:PandaRobot", "2:RobotState"]).get_data_value()
    # panda_temp_value = root_panda.get_child(["0:Objects", "2:PandaRobot", "2:RobotTempValue"]).get_data_value()
    value = panda_state.Value.Value
    if value != last_state["PandaRobot.State"]:
        last_state["PandaRobot.State"] = value
        data = {"name": "dtz.PandaRobot.RobotState",
                "phenomenonTime": panda_state.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat(),
                "resultTime": datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat(),
                "result": None,
                "parameters": dict({"state": value})}
        # print("publish panda state")
        publish_message(data)

def upsert_conbelt_state():
    conbelt_state = root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:ConBeltState"]).get_data_value()
    value = conbelt_state.Value.Value
    if value != last_state["Conbelt.State"]:
        last_state["Conbelt.State"] = value
        data = {"name": "dtz.ConveyorBelt.ConBeltState",
                "phenomenonTime": conbelt_state.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat(),
                "resultTime": datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat(),
                "result": None,
                "parameters": dict({"state": value})}
        # print("publish conbelt state")
        publish_message(data)

def upsert_conbelt_dist():
    conbelt_dist = root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:ConBeltDist"]).get_data_value()
    value = conbelt_dist.Value.Value
    if value != last_state["Conbelt.Dist"]:
        last_state["Conbelt.Dist"] = value
        data = {"name": "dtz.ConveyorBelt.ConBeltDist",
                "phenomenonTime": conbelt_dist.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat(),
                "resultTime": datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat(),
                "result": float(conbelt_dist.Value.Value)}
        # print("publish conbelt dist")
        publish_message(data)


def transform_name_to_id(data):
    data["Datastream"] = dict({"@iot.id": DATASTREAM_MAPPING[data["name"]]})
    x = data.pop("name")
    return data


def publish_message(message):
    message = transform_name_to_id(message)
    # Trigger any available delivery report callbacks from previous produce() calls
    producer.poll(0)
    producer.produce(KAFKA_TOPIC_metric, json.dumps(message).encode('utf-8'),
                     key=KAFKA_GROUP_ID, callback=delivery_report)


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
    producer.poll(0)
    producer.produce(KAFKA_TOPIC_logging, json.dumps(message).encode('utf-8'),
                     key=KAFKA_GROUP_ID, callback=logger_delivery_report)


def logger_delivery_report(err, msg):
    """ Called once for each message produced to indicate delivery result.
        Triggered by poll() or flush(). """
    if err is not None:
        kafka_logger('Message delivery failed: {}, {}, {}'.format(err, msg.topic(), msg.value()))
    else:
        print('Message delivered to {} [{}] with content: {}'.format(msg.topic(), msg.partition(),
                                                                     msg.value()))


if __name__ == "__main__":
    kafka_logger("OPC-UA Adapter for the Messaging system was started on host: {}"
                 .format(socket.gethostname()), level="INFO")
    kafka_logger("Kafka producer for was created, ready to stream", level="INFO")
    start()

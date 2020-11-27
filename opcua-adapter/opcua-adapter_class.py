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


# Messaging System Configurations
BOOTSTRAP_SERVERS = '192.168.48.81:9092,192.168.48.82:9092,192.168.48.83:9092'
KAFKA_GROUP_ID = "opc-adapter"
KAFKA_TOPIC_metric = "test-topic"  # "dtz.sensorthings"
KAFKA_TOPIC_logging = "dtz.logging"
SENSORTHINGS_HOST = "192.168.48.81"
SENSORTHINGS_PORT = "8084"

# sensorthings status
dir_path = os.path.dirname(os.path.realpath(__file__))
datastream_file = os.path.join(dir_path, "sensorthings", "id-structure.json")

sys.path.insert(0, "..")


class OPCUA_Adapter:
    def __init__(self):
        self.last_state = dict({"PandaRobot.State": None,
                                "Conbelt.State": None,
                                "Conbelt.Dist": None})

        self.client_panda = Client("opc.tcp://192.168.48.41:4840/freeopcua/server/")
        self.client_pixtend = Client("opc.tcp://192.168.48.42:4840/freeopcua/server/")
        self.client_panda.connect()
        self.client_pixtend.connect()

        # use freeopcua servie to investigate the trees
        self.root_panda = self.client_panda.get_root_node()
        self.root_pixtend = self.client_pixtend.get_root_node()

        # Messaging System
        conf = {'bootstrap.servers': BOOTSTRAP_SERVERS}
        self.producer = Producer(**conf)

        with open(datastream_file) as ds_file:
            self.DATASTREAM_MAPPING = json.load(ds_file)["Datastreams"]

    def disconnect(self):
        self.client_panda.disconnect()
        self.client_pixtend.disconnect()

    def start(self):
        try:
            while True:
                self.upsert_panda_state()
                self.upsert_conbelt_state()
                self.upsert_conbelt_dist()
                time.sleep(1)

        except KeyboardInterrupt:
            self.kafka_logger("KeyboardInterrrupt, gracefully closing", level="INFO")
        finally:
            self.disconnect()

    def upsert_panda_state(self):
        panda_state = self.root_panda.get_child(["0:Objects", "2:PandaRobot", "2:RobotState"]).get_data_value()
        # panda_temp_value = root_panda.get_child(["0:Objects", "2:PandaRobot", "2:RobotTempValue"]).get_data_value()
        value = panda_state.Value.Value
        if value != self.last_state["PandaRobot.State"]:
            self.last_state["PandaRobot.State"] = value
            data = {"name": "dtz.PandaRobot.RobotState",
                    "phenomenonTime": panda_state.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat(),
                    "resultTime": datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat(),
                    "result": None,
                    "parameters": dict({"state": value})}
            print("publish panda state")
            self.publish_message(data)

    def upsert_conbelt_state(self):
        conbelt_state = self.root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:ConBeltState"]).get_data_value()
        value = conbelt_state.Value.Value
        if value != self.last_state["Conbelt.State"]:
            self.last_state["Conbelt.State"] = value
            data = {"name": "dtz.ConveyorBelt.ConBeltState",
                    "phenomenonTime": conbelt_state.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat(),
                    "resultTime": datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat(),
                    "result": None,
                    "parameters": dict({"state": value})}
            print("publish conbelt state")
            self.publish_message(data)

    def upsert_conbelt_dist(self):
        conbelt_dist = self.root_pixtend.get_child(["0:Objects", "2:ConveyorBelt", "2:ConBeltDist"]).get_data_value()
        value = conbelt_dist.Value.Value
        if value != self.last_state["Conbelt.Dist"]:
            self.last_state["Conbelt.Dist"] = value
            data = {"name": "dtz.ConveyorBelt.ConBeltDist",
                    "phenomenonTime": conbelt_dist.SourceTimestamp.replace(tzinfo=pytz.UTC).isoformat(),
                    "resultTime": datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat(),
                    "result": float(conbelt_dist.Value.Value)}
            print("publish conbelt dist")
            self.publish_message(data)

    def transform_name_to_id(self, data):
        data["Datastream"] = dict({"@iot.id": self.DATASTREAM_MAPPING[data["name"]]})
        x = data.pop("name")
        return data

    def publish_message(self, message):
        message = self.transform_name_to_id(message)
        # Trigger any available delivery report callbacks from previous produce() calls
        self.producer.poll(0)
        self.producer.produce(KAFKA_TOPIC_metric, json.dumps(message).encode('utf-8'),
                         key=KAFKA_GROUP_ID, callback=self.delivery_report)

        print("sent:", str(message), str(message['Datastream']['@iot.id']).encode('utf-8'))

    def delivery_report(self, err, msg):
        """ Called once for each message produced to indicate delivery result.
            Triggered by poll() or flush(). """
        if err is not None:
            print('Message delivery failed: {}'.format(err))
        else:
            print('Message delivered to {} [{}] with content: {}'.format(msg.topic(), msg.partition(),
                                                                         msg.value()))

    def kafka_logger(self, payload, level="debug"):
        """
        Publish the canonical data format (Version: i-maintenance first iteration)
        to the Kafka Bus.
        Keyword argument:
        :param payload: message content as json or string
        :param level: log-level
        :return: None
        """
        print(level, payload)
        return
        message = {"Datastream": "dtz.opcua-adapter.logging",
                   "phenomenonTime": datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat(),
                   "result": payload,
                   "level": level,
                   "host": socket.gethostname()}

        print("Level: {} \tMessage: {}".format(level, payload))
        try:
            producer.produce(KAFKA_TOPIC_logging, json.dumps(message).encode('utf-8'),
                                  key=KAFKA_GROUP_ID)
            producer.poll(0)  # using poll(0), as Eden Hill mentions it avoids BufferError: Local: Queue full
            # producer.flush() poll should be faster here
        except Exception as e:
            print("Exception while sending metric: {} \non kafka topic: {}\n Error: {}"
                  .format(message, KAFKA_TOPIC_logging, e))


if __name__ == "__main__":
    
    opcua_adapter = OPCUA_Adapter()
    opcua_adapter.kafka_logger("Kafka producer for was created, ready to stream", level="INFO")
    opcua_adapter.start()

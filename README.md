# OPC-UA-Adapter
Connecting OPC-UA services with the Messaging System.
This component subscribes to topics from the Industrie 4.0 defacto standard
protocol OPC-UA and forwards them to the messaging system which is based on
Apache Kafka.
Therefore both services must be running:
* one or multiple OPC-UA-server
* [messaging-system](https://github.com/iot-salzburg/panta_rhei)


The OPC-UA Adapter is based on the components:
* Free-OPC-UA Client, [python-opcua](https://github.com/FreeOpcUa/python-opcua) version **0.98.7**
* Kafka Client [librdkafka](https://github.com/geeknam/docker-confluent-python) version **0.11.1**
* Python Kafka module [confluent-kafka-python](https://github.com/confluentinc/confluent-kafka-python) version **0.9.1.2**


## Contents

1. [Requirements](#requirements)
2. [Deployment](#deployment)
3. [Configuration](#configuration)
4. [Trouble-Shooting](#trouble-shooting)


## Requirements

1. Install [Docker](https://www.docker.com/community-edition#/download) version **1.10.0+**
2. Install [Docker Compose](https://docs.docker.com/compose/install/) version **1.6.0+**
   
3. Clone this repository
    ```bash
    git clone https://github.com/iot-salzburg/dtz_opcua_adapter
    cd dtz_opcua_adapter
    git clone https://github.com/iot-salzburg/panta_rhei opcua_adapter/panta_rhei > /dev/null 2>&1 || echo "Repo already exists"
    git -C opcua_adapter/panta_rhei/ checkout client_1v0
    git -C opcua_adapter/panta_rhei/ pull
    ```


## Basic Configuration
Now, the client can be imported and used in `opcua-adapter/opcua-adapter.py` with:
    
    ```python
    import os, sys
    from panta_rhei.client.digital_twin_client import DigitalTwinClient

    # Set the configs, create a new Digital Twin Instance and register file structure
    config = {"client_name": "opcua-adapter",
              "system": "at.srfg.iot.dtz",
              "gost_servers": "192.168.48.71:8082",
              "kafka_bootstrap_servers": "192.168.48.71:9092,192.168.48.72:9092,192.168.48.73:9092,192.168.48.74:9092,192.168.48.75:9092"}
    client = DigitalTwinClient(**config)
    client.register_new(instance_file=INSTANCES)
     ```
    
Note that the paths might be undetermined when executed locally, 
however using the `dockerfile.yml` it will work.


## Quickstart

The OPC-UA-Adapter uses SensorThings to semantically augment
the forwarded data. Data that is later on consumed by the
suggested [DB-Adapter](https://github.com/iot-salzburg/DB-Adapter/)
decodes the generic data format using the same SensorThings server.


### Creating the Kafka Topics

**only if not already done**

If zookeeper is specified by `:2181`, the local zookeeper service will be used. 
It may take some seconds until the new topics are distributed on each zookeeper instance in
a cluster setup.

```bash
/kafka/bin/kafka-topics.sh --zookeeper :2181 --list
/kafka/bin/kafka-topics.sh --zookeeper :2181 --create --partitions 3 --replication-factor 3 --config min.insync.replicas=2 --config cleanup.policy=compact --config retention.ms=241920000 --topic eu.srfg.iot.dtz.data
/kafka/bin/kafka-topics.sh --zookeeper :2181 --create --partitions 3 --replication-factor 3 --config min.insync.replicas=2 --config cleanup.policy=compact --config retention.ms=241920000 --topic eu.srfg.iot.dtz.external
/kafka/bin/kafka-topics.sh --zookeeper :2181 --create --partitions 3 --replication-factor 1 --config min.insync.replicas=1 --config cleanup.policy=compact --config retention.ms=241920000 --topic eu.srfg.iot.dtz.logging
/kafka/bin/kafka-topics.sh --zookeeper :2181 --list
```

### Testing

Configure the connection in the `docker-compose.yml`

```yaml
services:
  adapter:
    ...
    environment:
      # Panta Rhei configuration
      CLIENT_NAME: "opcua-adapter"
      SYSTEM_NAME: "at.srfg.iot.dtz"
      SENSORTHINGS_HOST: "192.168.48.71:8082"
      BOOTSTRAP_SERVERS: "192.168.48.71:9092,192.168.48.72:9092,192.168.48.73:9092,192.168.48.74:9092,192.168.48.75:9092"
```

Using `docker-compose`: This depends on the **Panta Rhei Stack** and
configured `instance_file`. Other settings are configured in the source 
code of `opcua-adapter/opcua-adapter.py`.


```bash
cd dtz_opcua-adapter
sudo docker-compose up --build -d
```

The flag `-d` stands for running it in background (detached mode):

Watch the logs with:
```bash
sudo docker-compose logs -f
```


## Deployment in the docker swarm

Using `docker stack`:

If not already done, add a registry instance to register the image
```bash
sudo docker service create --name registry --publish published=5001,target=5000 registry:2
curl 127.0.0.1:5001/v2/
```
This should output `{}`:

If running with docker-compose works, the stack will start by running:

```bash
sh start-opcua-adapter.sh
```

Watch if everything worked fine with:

```bash
./show-adapter.sh
docker service logs -f add-opcua
```


## Configuration

The asset structure is configured in the `instance.json` file to
augment the incoming OPC-UA messages with metadata stored on the
sensorthings server.
If the structure is changed the opcua-adapter has to be restarted in order to
update the structure in the SensorThings server.


## Trouble-shooting

#### Can't apt-get update in Dockerfile:
Restart the service

```sudo service docker restart```

or add the file `/etc/docker/daemon.json` with the content:
```
{
    "dns": [your_dns, "8.8.8.8", "8.8.8.4"]
}
```
where `your_dns` can be found with the command:

```bash
nmcli device show [interfacename] | grep IP4.DNS
```

####  Traceback of non zero code 4 or 128:

Restart service with
```sudo service docker restart```

or add your dns address as described above

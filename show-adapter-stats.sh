#!/usr/bin/env bash
echo "Printing 'docker service ls | grep add-opcua':"
docker service ls | grep add-opcua
echo ""
echo "Printing 'docker service ps add-opcua':"
docker service ps add-opcua

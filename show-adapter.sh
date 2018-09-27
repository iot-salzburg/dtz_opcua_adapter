#!/usr/bin/env bash
echo "Printing 'docker service ls | grep add-opcua':"
docker service ls | grep opcua
echo ""
echo "Printing 'docker service ps add-opcua_adapter':"
docker service ps opcua_adapter

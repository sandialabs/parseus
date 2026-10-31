#!/bin/sh

# Set umask to share file permissions between containers
umask 0022
exec "$@"

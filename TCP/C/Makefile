# Define the directories
CLIENT_DIR = client
SERVER_DIR = server

# Define the source files
CLIENT_SRC = $(CLIENT_DIR)/TCPclient.c
SERVER_SRC = $(SERVER_DIR)/TCPserver.c

# Define the output executables
CLIENT_EXEC = $(CLIENT_DIR)/TCPclient
SERVER_EXEC = $(SERVER_DIR)/TCPserver

# Compiler and flags
CC = gcc
CFLAGS = -Wall -Wextra -O2

# Default target
all: $(CLIENT_EXEC) $(SERVER_EXEC)

# Compile the client
$(CLIENT_EXEC): $(CLIENT_SRC)
	$(CC) $(CFLAGS) -o $@ $<

# Compile the server
$(SERVER_EXEC): $(SERVER_SRC)
	$(CC) $(CFLAGS) -o $@ $<

# Clean up compiled files
clean:
	rm -f $(CLIENT_EXEC) $(SERVER_EXEC)

.PHONY: all clean run_server run_client run


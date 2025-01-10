# Define the directories
CLIENT_DIR = client
SERVER_DIR = server

# Define the source files
CLIENT_SRC = $(CLIENT_DIR)/testClient.c
SERVER_SRC = $(SERVER_DIR)/testServer.c

# Define the output executables
CLIENT_EXEC = $(CLIENT_DIR)/testClient
SERVER_EXEC = $(SERVER_DIR)/testServer

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


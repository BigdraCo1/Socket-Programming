#include <netinet/in.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
#include <arpa/inet.h>

#define BUFFER_SIZE 1024

void error(char *msg) {
  perror(msg);
  exit(1);
}

int network_socket;

void find_new_line(int size, char *buffer) {
  for (int i = 0; i < size; i++) {
    if (buffer[i] == '\n') {
      memset(&buffer[i], '\0', sizeof(char));
      break;
    }
  }
}

void *read_from_server(void *arg) {
  char buff[BUFFER_SIZE];
  int n;

  while (1) {
    bzero(buff, BUFFER_SIZE);
    n = read(network_socket, buff, BUFFER_SIZE);
    if (n < 0) {
      error("Error on reading.");
    }
    find_new_line(BUFFER_SIZE, &buff);

    if (strncmp("Zhaijian", buff, 8) == 0) {
      printf("[+]Server closed the connection. Exiting...\n");
      break;
    } else {
      printf("%s <-- From server\n", buff);
    }
  }

  close(network_socket);
  exit(0);
  return NULL;
}

int main(int argc, char *argv[]) {

  if (argc != 3) {
    fprintf(stderr, "Usage: %s <IP Address> <Port>\n", argv[0]);
    exit(1);
  }

  char *ip_address = argv[1];
  int port = atoi(argv[2]);

  char buff[BUFFER_SIZE];
  int n;

  // Create a socket
  network_socket = socket(AF_INET, SOCK_STREAM, 0);
  if (network_socket < 0) {
    error("Error creating socket.");
  }
  printf("[+]Client socket created successfully.\n");

  struct sockaddr_in servaddr;
  bzero(&servaddr, sizeof(servaddr));
  servaddr.sin_family = AF_INET;
  servaddr.sin_port = htons(port);
  if (inet_pton(AF_INET, ip_address, &servaddr.sin_addr) <= 0) {
    error("Invalid address/ Address not supported.");
  }

  if (connect(network_socket, (struct sockaddr *)&servaddr, sizeof(servaddr)) <
      0) {
    error("Connection failed.");
  }
  printf("[+]Connected to the server.\n");

  // Create a thread to handle reading from the server
  pthread_t read_thread;
  if (pthread_create(&read_thread, NULL, read_from_server, NULL) != 0) {
    error("Error creating thread.");
  }

  // Main thread handles user input
  while (1) {
    bzero(buff, BUFFER_SIZE);
    fgets(buff, BUFFER_SIZE, stdin);
    n = write(network_socket, buff, strlen(buff));
    if (n < 0) {
      error("Error on writing.");
    }

    // Check for "Zhaijian" in user input to terminate
    if (strncmp("Zhaijian", buff, 8) == 0) {
      printf("[+]Client closing connection. Exiting...\n");
      break;
    }
  }

  // Close the socket and join the thread
  close(network_socket);
  pthread_join(read_thread, NULL);
  return 0;
}

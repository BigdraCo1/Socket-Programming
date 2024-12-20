#include <netinet/in.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#define PORT 9000
#define BUFFER_SIZE 1024

void error(char *msg) {
  perror(msg);
  exit(1);
}

int network_socket;

void *read_from_server(void *arg) {
  char buff[BUFFER_SIZE];
  int n;

  while (1) {
    bzero(buff, BUFFER_SIZE);
    n = read(network_socket, buff, BUFFER_SIZE);
    if (n < 0) {
      error("Error on reading.");
    }

    printf("\nServer: %s\n", buff);

    if (strncmp("Zhaijian", buff, 8) == 0) {
      printf("[+]Server closed the connection. Exiting...\n");
      close(network_socket);
      exit(0);
    }
  }

  return NULL;
}

int main() {
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
  servaddr.sin_port = htons(PORT);
  servaddr.sin_addr.s_addr = inet_addr("127.0.0.1");

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
    printf("Client :");
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

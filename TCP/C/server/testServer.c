#include <netinet/in.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <sys/types.h>

#define PORT 9000
#define BUFFER_SIZE 1024

void error(char *msg) {
  perror(msg);
  exit(1);
}

int newSocket;

void find_new_line(int size, char *buffer) {
  for (int i = 0; i < size; i++) {
    if (buffer[i] == '\n') {
      memset(&buffer[i], '\0', sizeof(char));
      break;
    }
  }
}

void *read_socket(void *arg) {
  char buff[BUFFER_SIZE];
  bzero(buff, BUFFER_SIZE);
  while (1) {
    int n = read(newSocket, buff, BUFFER_SIZE);
    if (n < 0) {
      error("Error reading.");
    }
    find_new_line(BUFFER_SIZE, &buff);
    printf("%s <--- From client\n", buff);
    if (strncmp("Zhaijian", buff, 8) == 0) {
      printf("[+]Server closed the connection. Exiting...\n");
      close(newSocket);
      exit(0);
    }
  }

  return NULL;
}

int main() {
  pthread_t rT;
  int networkSocket, n;
  struct sockaddr_in newAddr, serverAddr;

  socklen_t addr_size;
  char buff[BUFFER_SIZE];

  networkSocket = socket(AF_INET, SOCK_STREAM, 0);
  printf("[+]Server Socket created successfully\n");
  // initializes the struct to all zeros to ensure no garbage values
  bzero(&serverAddr, sizeof(serverAddr));
  serverAddr.sin_family = AF_INET;
  serverAddr.sin_port = htons(PORT);
  serverAddr.sin_addr.s_addr = inet_addr("127.0.0.1");

  // bind socket
  bind(networkSocket, (struct sockaddr *)&serverAddr, sizeof(serverAddr));
  printf("[+]Bind to the port %d\n", PORT);

  // Listen new socket
  listen(networkSocket, SOMAXCONN);
  printf("[+]Listening...\n");
  addr_size = sizeof(newAddr);

  // Client socket
  newSocket = accept(networkSocket, (struct sockaddr *)&newAddr, &addr_size);

  if (pthread_create(&rT, NULL, read_socket, NULL) != 0) {
    error("Error can't create thread");
  }

  while (1) {
    bzero(buff, BUFFER_SIZE);
    fgets(buff, BUFFER_SIZE, stdin);
    n = write(newSocket, buff, strlen(buff));
    if (n < 0)
      error("Error on writing.");
    if (strncmp("Zhaijian", buff, 8) == 0)
      break;
  }
  pthread_join(rT, NULL);

  close(newSocket);
  close(networkSocket);
  return 0;
}

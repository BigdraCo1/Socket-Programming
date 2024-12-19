#include <netinet/in.h>
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

int main() {
  int networkSocket, newSocket, n;
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

  while (1) {
    bzero(buff, BUFFER_SIZE);
    n = read(newSocket, buff, BUFFER_SIZE);
    if (n < 0)
      error("Error on reading.");
    printf("Client : %s\n", buff);

    bzero(buff, BUFFER_SIZE);
    fgets(buff, BUFFER_SIZE, stdin);
    n = write(newSocket, buff, strlen(buff));
    if (n < 0)
      error("Error on writing.");
    if (strncmp("Zhaijian", buff, 8) == 0)
      break;
  }

  close(newSocket);
  close(networkSocket);
  return 0;
}

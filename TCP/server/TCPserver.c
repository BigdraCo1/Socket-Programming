#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>

#define PORT 9000
#define BUFFER_SIZE 1024

int main() {
  int networkSocket;
  struct sockaddr_in serverAddr;

  int newSocket;
  struct sockaddr_in newAddr;

  socklen_t addr_size;
  char buff[BUFFER_SIZE];

  networkSocket = socket(AF_INET, SOCK_STREAM, 0);
  // initializes the struct to all zeros to ensure no garbage values
  bzero(&serverAddr, sizeof(serverAddr));
  serverAddr.sin_family = AF_INET;
  serverAddr.sin_port = htons(PORT);
  serverAddr.sin_addr.s_addr = inet_addr("127.0.0.1");

  // bind socket
  bind(networkSocket, (struct sockaddr *)&serverAddr, sizeof(serverAddr));

  listen(networkSocket, SOMAXCONN);
  addr_size = sizeof(newAddr);

  accept(newSocket, (struct sockaddr *)&newAddr, &addr_size);

  strcpy(buff, "Nigga\n");
  send(newSocket, buff, strlen(buff), 0);
}

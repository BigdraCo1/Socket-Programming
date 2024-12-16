#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>

#define PORT 9000
#define BUFFER_SIZE 1024 

int main(){
  
  char buff[BUFFER_SIZE];

  // create a socket
  int network_socket;
  network_socket = socket(AF_INET, SOCK_STREAM, 0); // int socket(int domain, int type, int protocol); 0 in protocol is TCP ; CAN SEE IN TERMINAL : `$ man socket`
  
  struct sockaddr_in servaddr;
  // initializes the struct to all zeros to ensure no garbage values
  bzero(&servaddr, sizeof(servaddr));
  servaddr.sin_family = AF_INET;
  servaddr.sin_port = htons(PORT);
  servaddr.sin_addr.s_addr = inet_addr("127.0.0.1");

  if (connect(network_socket, (struct sockaddr *)&servaddr, sizeof(servaddr)) < 0) { // int connect(int socket, const struct sockaddr *address, socklen_t address_len);
    printf("error\n");
    return 1;
  }

  recv(network_socket, buff, BUFFER_SIZE, 0); // int recv(int socket, char *buffer, int length, int flags);
  printf("Data Recieve : %s\n", buff);

  close(network_socket);
  return 0;
}


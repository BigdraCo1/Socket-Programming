#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>

#define PORT 9000
#define BUFFER_SIZE 1024

void error(char *msg) {
  perror(msg);
  exit(1);
}

int main() {

  char buff[BUFFER_SIZE];

  // create a socket
  int network_socket, n;
  network_socket =
      socket(AF_INET, SOCK_STREAM,
             0); // int socket(int domain, int type, int protocol); 0 in
                 // protocol is TCP ; CAN SEE IN TERMINAL : `$ man socket`
  printf("[+]Server Socket created successfully\n");

  struct sockaddr_in servaddr;
  // initializes the struct to all zeros to ensure no garbage values
  bzero(&servaddr, sizeof(servaddr));
  servaddr.sin_family = AF_INET;
  servaddr.sin_port = htons(PORT);
  servaddr.sin_addr.s_addr = inet_addr("127.0.0.1");

  if (connect(network_socket, (struct sockaddr *)&servaddr, sizeof(servaddr)) <
      0) { // int connect(int socket, const struct sockaddr *address, socklen_t
           // address_len);
    printf("error\n");
    return 1;
  }
  printf("[+]Connected to the Server\n");

  while (1) {
    bzero(buff, BUFFER_SIZE);
    fgets(buff, BUFFER_SIZE, stdin);
    n = write(network_socket, buff, strlen(buff));
    if (n < 0)
      error("Error on writing.");

    bzero(buff, BUFFER_SIZE);
    n = read(network_socket, buff, BUFFER_SIZE);
    if (n < 0)
      error("Error on reading");
    printf("Server : %s\n", buff);
    if (strncmp("Zhaijian", buff, 8) == 0)
      break;
  }
  close(network_socket);
  return 0;
}

package main

import (
	"fmt"
	"net"
	"os"
)

func handleWrite(connection *net.Conn) {
	for {
		var buff string
		fmt.Scanln(&buff)
		buff = buff + "\n"
		_, err := (*connection).Write([]byte(buff))
		if buff == "Zhaijian\n" {
			os.Exit(0)
		}
		if err != nil {
			fmt.Println(err)
		}
	}
}

func handleRead(connection *net.Conn) {
	for {
		var buf [512]byte
		n, err := (*connection).Read([]byte(buf[:]))
		if err != nil {
			fmt.Println(err)
		}
		fmt.Println(string(buf[:n-1]))
		if string(buf[:n-1]) == "Zhaijian" {
			os.Exit(0)
		}
	}
}

func main() {
	conn, err := net.Dial("tcp", "127.0.0.1:9999")
	if err != nil {
		fmt.Println(err)
		os.Exit(0)
	}
	defer conn.Close()

	go handleWrite(&conn)
	handleRead(&conn)
}

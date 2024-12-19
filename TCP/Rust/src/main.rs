use std::io::prelude::*;
use std::net::TcpStream;

fn main() -> std::io::Result<()> {
    let mut stream = TcpStream::connect("127.0.0.1:34254")?;

    stream.write(b"Hello, world!\n")?;
    let mut buffer = [0; 128];
    stream.read(&mut buffer)?;
    println!("Received: {}", String::from_utf8_lossy(&buffer));
    Ok(())
}
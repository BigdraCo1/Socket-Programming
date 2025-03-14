import os
import sys
import socket
import time
import struct
import logging
import argparse
import threading
from packet import *
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('FastServer')

# Server constants
SERVER_TIMEOUT = 0.5  # Reduced for faster response
CLEANUP_INTERVAL = 30  # Clean up stale connections every 30 seconds
MAX_FRAGMENT_AGE = 60  # Clean up fragments older than 60 seconds
MAX_OUT_OF_ORDER_BUFFER = 100  # Maximum out-of-order packets to store

class OutOfOrderBuffer:
    """Efficiently handles out-of-order packets and sequence tracking"""
    
    def __init__(self):
        """Initialize buffer with improved tracking"""
        self.packets = {}  # seq_num -> (data, timestamp, has_more)
        self.expected_seq = None  # Next expected sequence number
        self.has_final = False  # Whether we have seen the final fragment
        self.last_activity = time.time()
        self.highest_seq_received = 0  # Track highest sequence received
        self.received_ranges = []  # List of (start, end) ranges received
    
    def add_packet(self, seq_num, data, has_more=False):
        """Add a packet to the buffer with improved tracking"""
        # Update timestamp
        self.last_activity = time.time()
        
        # Ignore duplicates
        if seq_num in self.packets:
            return False
            
        # Store packet
        self.packets[seq_num] = (data, time.time(), has_more)
        
        # Update expected_seq if this is the first packet
        if self.expected_seq is None:
            self.expected_seq = seq_num
            
        # Update highest sequence seen
        self.highest_seq_received = max(self.highest_seq_received, seq_num + len(data))
            
        # Mark if this is final fragment
        if not has_more:
            self.has_final = True
            
        # Update received ranges for better gap detection
        self._update_ranges(seq_num, seq_num + len(data))
            
        return True
        
    def _update_ranges(self, start, end):
        """Update the received ranges when a new packet arrives"""
        # No existing ranges, just add this one
        if not self.received_ranges:
            self.received_ranges.append((start, end))
            return
            
        # Try to merge with existing ranges
        new_ranges = []
        merged = False
        
        for r_start, r_end in self.received_ranges:
            # Check if new range overlaps or is adjacent to this range
            if end < r_start - 1 or start > r_end + 1:
                # No overlap, keep existing range unchanged
                new_ranges.append((r_start, r_end))
            else:
                # Ranges overlap or are adjacent, merge them
                new_start = min(start, r_start)
                new_end = max(end, r_end)
                new_ranges.append((new_start, new_end))
                merged = True
                
        # If we didn't merge with any existing range, add as new
        if not merged:
            new_ranges.append((start, end))
            
        # Sort and consolidate ranges
        new_ranges.sort()
        self.received_ranges = []
        
        for r in new_ranges:
            if not self.received_ranges or r[0] > self.received_ranges[-1][1]:
                self.received_ranges.append(r)
            else:
                # Merge overlapping ranges
                last_start, last_end = self.received_ranges[-1]
                self.received_ranges[-1] = (last_start, max(last_end, r[1]))
    
    def get_in_order_data(self):
        """Get data that is ready to be processed in order with improved handling"""
        if not self.packets or self.expected_seq is None:
            return None
            
        # Check if we have any packets to process
        if not any(isinstance(k, int) for k in self.packets.keys()):
            return None
            
        # First check if we have the next expected packet
        if self.expected_seq not in self.packets:
            # If we've waited a while and have the final fragment, try processing all data
            if self.has_final and time.time() - self.last_activity > 2.0:
                logger.info(f"Processing out-of-order data after timeout, expected={self.expected_seq}")
                if len(self.packets) > 0:  # Only if we have some data
                    return self.get_all_data()
            return None
            
        # Collect contiguous packets
        data_segments = []
        current_seq = self.expected_seq
        
        while current_seq in self.packets:
            packet_data, _, has_more = self.packets[current_seq]
            data_segments.append(packet_data)
            
            # Remove from buffer
            next_seq = current_seq + len(packet_data)
            self.packets.pop(current_seq)
            
            # Update expected sequence
            current_seq = next_seq
        
        # Update expected sequence for next time
        self.expected_seq = current_seq
        
        # Combine segments
        if data_segments:
            return b''.join(data_segments)
        return None
    
    def get_all_data(self):
        """Get all data in the buffer, sorted by sequence number"""
        if not self.packets:
            return None
            
        # Sort packets by sequence number
        sorted_packets = sorted(self.packets.items())
        
        # Combine data
        data_segments = [data for seq, (data, _, _) in sorted_packets]
        return b''.join(data_segments)
    
    def has_gaps(self):
        """Check if there are gaps in the received data"""
        if not self.received_ranges:
            return False
            
        # If we have more than one range, or the first range doesn't start at expected_seq
        if len(self.received_ranges) > 1:
            return True
            
        if self.expected_seq is not None and self.received_ranges[0][0] > self.expected_seq:
            return True
            
        return False
    
    def clear(self):
        """Clear the buffer"""
        self.packets.clear()
        self.expected_seq = None
        self.has_final = False
    
    def is_stale(self, max_age=MAX_FRAGMENT_AGE):
        """Check if buffer is stale (no recent activity)"""
        return time.time() - self.last_activity > max_age
        
    def get_size(self):
        """Get number of packets in buffer"""
        return len(self.packets)
    
    def is_ready_for_flush(self):
        """Check if buffer should be flushed (has final and stale)"""
        # If we have the final fragment and no activity for a while
        return self.has_final and (time.time() - self.last_activity > 2.0)

class FastServer:
    def __init__(self, ip, port, output_dir="received_files"):
        """Initialize server with address and output directory"""
        self.ip = ip
        self.port = port
        
        # Create socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((ip, port))
        self.socket.settimeout(SERVER_TIMEOUT)
        
        # Try to optimize socket
        try:
            # Larger receive buffer
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4194304)  # 4MB
        except:
            pass
        
        # Set up output directory
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        logger.info(f"Files will be saved to: {self.output_dir}")
        
        # State tracking
        self.connections = {}  # client_addr -> connection state
        self.out_of_order_buffers = defaultdict(OutOfOrderBuffer)  # client_addr -> buffer
        self.file_info = {}  # client_addr -> file info dict
        self.file_handles = {}  # client_addr -> open file handle
        
        # Control
        self.running = True
        
        logger.info(f"Enhanced server started on {ip}:{port}")
    
    def run(self):
        """Main server loop"""
        # Start cleanup thread
        cleanup_thread = threading.Thread(target=self._cleanup_loop)
        cleanup_thread.daemon = True
        cleanup_thread.start()
        
        # Start out-of-order processing thread
        buffer_thread = threading.Thread(target=self._process_buffers_loop)
        buffer_thread.daemon = True
        buffer_thread.start()
        
        try:
            while self.running:
                try:
                    # Wait for packet
                    packet, client_addr = self.socket.recvfrom(65535)
                    
                    # Process packet
                    self._handle_packet(packet, client_addr)
                    
                except socket.timeout:
                    # Normal timeout, just continue
                    continue
                except KeyboardInterrupt:
                    logger.info("Server shutting down...")
                    self.running = False
                    break
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
        finally:
            # Stop threads
            self.running = False
            
            # Wait for threads to finish
            cleanup_thread.join(timeout=1.0)
            buffer_thread.join(timeout=1.0)
            
            # Close all file handles
            for handle in self.file_handles.values():
                try:
                    handle.close()
                except:
                    pass
            
            # Close socket
            self.socket.close()
    
    def _handle_packet(self, packet, client_addr):
        """Process received packet"""
        # Try fast parsing first for speed
        parsed = parse_packet_fast(packet)
        if not parsed:
            # Fall back to full parsing
            parsed = parse_packet(packet)
            if not parsed:
                # Invalid packet
                return
        
        # Extract data based on packet format
        if len(parsed) == 4:  # Fast parse result
            seq_num, ack_num, flags, payload = parsed
        else:  # Full parse result
            seq_num, ack_num, flags, _, payload = parsed
        
        # Handle by packet type
        if flags == SYN:
            self._handle_syn(client_addr, seq_num)
        elif flags == ACK:
            # Just update timestamp for pure ACKs
            if client_addr in self.connections:
                self.connections[client_addr]['time'] = time.time()
        elif flags == FIN:
            self._handle_fin(client_addr, seq_num)
        elif payload:
            # Data packet
            has_more = is_more_fragments(flags)
            self._handle_data_with_seq(client_addr, seq_num, payload, has_more)
    
    def _handle_syn(self, client_addr, seq_num):
        """Handle connection request with improved reliability"""
        # Generate sequence number - or reuse existing one if reconnection
        if client_addr in self.connections:
            # Reconnection attempt - use existing sequence
            server_seq = self.connections[client_addr]['seq']
            logger.info(f"Reconnection from {client_addr}")
        else:
            # New connection
            server_seq = generate_initial_seq_num()
            logger.info(f"New connection from {client_addr}")
        
        # Store or update connection
        self.connections[client_addr] = {
            'seq': server_seq,
            'ack': seq_num + 1,  # Next expected from client
            'time': time.time()
        }
        
        # Send SYN-ACK - retry multiple times for reliability
        syn_ack = create_packet(server_seq, seq_num + 1, SYN_ACK)
        
        # Send multiple times to improve reliability (client will deduplicate)
        attempts = 0
        max_attempts = 3
        
        while attempts < max_attempts:
            try:
                self.socket.sendto(syn_ack, client_addr)
                attempts += 1
                
                # Brief pause between attempts
                if attempts < max_attempts:
                    time.sleep(0.01)
            except Exception as e:
                logger.error(f"Error sending SYN-ACK: {e}")
                break
    
    def _handle_data_with_seq(self, client_addr, seq_num, payload, has_more):
        """Handle data packet with improved ACK handling for sliding window clients"""
        # Skip if client not connected
        if client_addr not in self.connections:
            return
            
        # Update connection timestamp
        self.connections[client_addr]['time'] = time.time()
        
        # Calculate next sequence number (for ACK)
        next_seq = seq_num + len(payload)
        
        # Add to out-of-order buffer
        buffer = self.out_of_order_buffers[client_addr]
        newly_added = buffer.add_packet(seq_num, payload, has_more)
        
        # Try to get data in correct order
        in_order_data = buffer.get_in_order_data()
        
        if in_order_data:
            # Process the in-order data
            self._process_data(client_addr, in_order_data)
        
        # Always send immediate ACK with correct expected sequence - essential for sliding window
        if buffer.expected_seq is not None:
            # ACK should be the next expected byte
            ack_value = buffer.expected_seq
        else:
            # Fallback - ACK for the current packet
            ack_value = next_seq
        
        # Send ACK - essential for sliding window
        ack = create_packet_fast(self.connections[client_addr]['seq'], ack_value, ACK)
        self.socket.sendto(ack, client_addr)
        
        # For newly detected gaps, send duplicate ACKs to trigger fast retransmit
        if newly_added and buffer.has_gaps() and buffer.expected_seq is not None:
            # Send two more ACKs to help reach the triple duplicate ACK threshold faster
            # This helps with triggering fast retransmit on the client side
            for _ in range(2):
                try:
                    time.sleep(0.001)  # Tiny delay between ACKs
                    self.socket.sendto(ack, client_addr)
                except:
                    pass
    
    def _process_data(self, client_addr, data):
        """Process data that is now in order"""
        try:
            if data.startswith(b'FILE:'):
                # File metadata
                self._handle_file_metadata(client_addr, data)
            elif client_addr in self.file_handles:
                # File data
                self._write_file_data(client_addr, data)
            else:
                # Regular message
                try:
                    message = data.decode('utf-8', errors='replace')
                    logger.info(f"Message from {client_addr}: {message[:100]}")
                except:
                    logger.info(f"Binary data from {client_addr}: {len(data)} bytes")
        except Exception as e:
            logger.error(f"Error processing data: {e}")
    
    def _handle_fin(self, client_addr, seq_num):
        """Handle connection termination"""
        if client_addr not in self.connections:
            return
        
        # Send FIN-ACK
        fin_ack = create_packet_fast(self.connections[client_addr]['seq'], seq_num + 1, FIN_ACK)
        self.socket.sendto(fin_ack, client_addr)
        
        # Close any open file
        if client_addr in self.file_handles:
            try:
                self._finalize_file(client_addr)
            except:
                pass
        
        # Clean up
        self.out_of_order_buffers.pop(client_addr, None)
        self.connections[client_addr]['time'] = time.time()  # Update for cleanup timing
        
        logger.info(f"Connection closed: {client_addr}")
    
    def _cleanup_loop(self):
        """Background thread for cleaning up stale resources"""
        while self.running:
            try:
                # Sleep first
                time.sleep(CLEANUP_INTERVAL)
                
                # Skip if server is stopping
                if not self.running:
                    break
                
                now = time.time()
                
                # Clean stale connections
                stale_clients = []
                for addr, conn in self.connections.items():
                    if now - conn['time'] > SERVER_TIMEOUT * 10:  # 10x timeout
                        stale_clients.append(addr)
                
                # Remove stale clients and their resources
                for addr in stale_clients:
                    if addr in self.file_handles:
                        try:
                            self.file_handles[addr].close()
                            logger.warning(f"Closed stale file transfer: {self.file_info[addr]['name']}")
                        except:
                            pass
                    
                    self.file_handles.pop(addr, None)
                    self.file_info.pop(addr, None)
                    self.out_of_order_buffers.pop(addr, None)
                    self.connections.pop(addr, None)
                
                if stale_clients:
                    logger.info(f"Cleaned up {len(stale_clients)} stale connections")
                
                # Clean old fragments
                frag_count = 0
                for addr in list(self.out_of_order_buffers.keys()):
                    if addr not in self.connections:
                        # Client no longer connected
                        self.out_of_order_buffers.pop(addr, None)
                        frag_count += 1
                        continue
                    
                    # Check for old fragments
                    buffer = self.out_of_order_buffers[addr]
                    if buffer.is_stale():
                        self.out_of_order_buffers.pop(addr, None)
                        frag_count += 1
                
                if frag_count:
                    logger.debug(f"Cleaned up {frag_count} old fragments")
                
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    def _process_buffers_loop(self):
        """Background thread for processing buffers with improved error recovery"""
        while self.running:
            try:
                time.sleep(0.1)  # Short sleep to avoid busy-wait
                
                for client_addr, buffer in list(self.out_of_order_buffers.items()):
                    # Skip if client not connected
                    if client_addr not in self.connections:
                        continue
                    
                    # Check if buffer is ready for forcing processing
                    force_process = False
                    
                    # Check buffer conditions
                    if buffer.is_ready_for_flush():
                        force_process = True
                    elif buffer.has_final and buffer.get_size() > 0:
                        # We have the final fragment, but may still be missing data
                        # Check how long we've been waiting
                        if time.time() - buffer.last_activity > 5.0:  # 5 seconds inactivity
                            logger.warning(f"Processing incomplete buffer after timeout: {buffer.get_size()} packets")
                            force_process = True
                    
                    # Process buffer if needed
                    if force_process:
                        data = buffer.get_all_data()
                        if data:
                            self._process_data(client_addr, data)
                            logger.debug(f"Force processed buffered data: {len(data)} bytes from {client_addr}")
                        
                        # Clear buffer
                        buffer.clear()
                        
                        # Send an ACK indicating we've processed everything
                        if client_addr in self.connections:
                            ack = create_packet_fast(
                                self.connections[client_addr]['seq'],
                                buffer.highest_seq_received, 
                                ACK
                            )
                            self.socket.sendto(ack, client_addr)
                            
            except Exception as e:
                logger.error(f"Error in buffer processing loop: {e}")

    def _handle_file_metadata(self, client_addr, payload):
        """Process file metadata"""
        try:
            # Parse metadata in format: FILE:name:size
            meta = payload.decode('utf-8')
            parts = meta.split(':', 2)
            if len(parts) != 3 or parts[0] != 'FILE':
                logger.error(f"Invalid file metadata format: {meta}")
                return
            
            # Extract name and size
            name = parts[1]
            size = int(parts[2])
            
            # Create safe output filename
            safe_name = os.path.basename(name)
            if not safe_name:
                safe_name = f"file_{int(time.time())}"
            
            # Avoid filename conflicts
            path = os.path.join(self.output_dir, safe_name)
            if os.path.exists(path):
                base, ext = os.path.splitext(safe_name)
                path = os.path.join(self.output_dir, f"{base}_{int(time.time())}{ext}")
            
            # Store file info
            self.file_info[client_addr] = {
                'name': safe_name,
                'size': size,
                'path': path,
                'received': 0,
                'start_time': time.time()
            }
            
            # Open file
            self.file_handles[client_addr] = open(path, 'wb', buffering=4194304)  # 4MB buffer
            
            logger.info(f"Receiving file: {safe_name} ({size:,} bytes)")
            
        except Exception as e:
            logger.error(f"Error processing file metadata: {e}")
    
    def _write_file_data(self, client_addr, data):
        """Write received file data"""
        if client_addr not in self.file_handles or client_addr not in self.file_info:
            return
        
        try:
            # Write data
            self.file_handles[client_addr].write(data)
            
            # Update received counter
            self.file_info[client_addr]['received'] += len(data)
            received = self.file_info[client_addr]['received']
            size = self.file_info[client_addr]['size']
            
            # Log progress occasionally
            if size > 1000000:  # Only for files > 1MB
                progress = int((received / size) * 100)
                # Log every 10% for larger files
                if received % (size // 10) < len(data) and progress > 0:
                    elapsed = time.time() - self.file_info[client_addr]['start_time']
                    rate = received / (elapsed * 1024) if elapsed > 0 else 0
                    logger.info(f"File transfer: {progress}% ({received:,}/{size:,} bytes), {rate:.2f} KB/s")
            
            # Check if file is complete
            if received >= size:
                self._finalize_file(client_addr)
                
        except Exception as e:
            logger.error(f"Error writing file data: {e}")
    
    def _finalize_file(self, client_addr):
        """Finalize file transfer"""
        try:
            # Close file handle
            self.file_handles[client_addr].close()
            
            # Get stats
            info = self.file_info[client_addr]
            elapsed = time.time() - info['start_time']
            rate = info['size'] / (elapsed * 1024) if elapsed > 0 else 0
            
            logger.info(f"File transfer complete: {info['name']}")
            logger.info(f"Size: {info['size']:,} bytes, Time: {elapsed:.2f}s, Rate: {rate:.2f} KB/s")
            logger.info(f"Saved to: {info['path']}")
            
            # Clean up
            self.file_handles.pop(client_addr)
            self.file_info.pop(client_addr)
            
        except Exception as e:
            logger.error(f"Error finalizing file: {e}")

def main():
    """Server entry point"""
    parser = argparse.ArgumentParser(description="Fast UDP file transfer server")
    parser.add_argument("ip", help="IP address to listen on")
    parser.add_argument("port", type=int, help="Port to listen on")
    parser.add_argument("--dir", "-d", default="received_files", help="Output directory")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # Create and start server
    server = FastServer(args.ip, args.port, args.dir)
    
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    
    return 0

if __name__ == "__main__":
    sys.exit(main())